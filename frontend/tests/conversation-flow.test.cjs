const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const ts = require("typescript");

// Replay the real event handlers with controlled network responses, without
// introducing a DOM runner or contacting model services.
const source = ts.createSourceFile("App.tsx", fs.readFileSync(path.join(__dirname, "../src/App.tsx"), "utf8"),
  ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const names = ["handleValidation", "handleSelectConversation", "invalidateConversationView", "handleNewConversation",
  "handleLogout", "handleAuth", "handleDeleteConversation", "toChatMessage"];
const handlers = [];
function visit(node) {
  if (ts.isFunctionDeclaration(node) && names.includes(node.name?.text)) handlers.push(node.getText(source));
  ts.forEachChild(node, visit);
}
visit(source);
const js = ts.transpileModule(handlers.join("\n"), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.None }
}).outputText;

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function harness() {
  const noop = () => {};
  let id = 0;
  const ctx = {
    console: { error: noop }, AbortController, window: { innerWidth: 1400 }, RESET_REASON: "reset",
    abortRun: noop, objectUrlsRef: { current: new Set() }, historyAbortRef: { current: null },
    viewEpochRef: { current: 0 }, pendingValidationsRef: { current: new Set() },
    setImageDraft(value) { ctx.imageDraft = value; }, setInputValue(value) { ctx.inputValue = value; },
    setCurrentUser(value) { ctx.currentUser = value; },
    URL: { revokeObjectURL: noop },
    setConversations(value) { ctx.conversations = typeof value === "function" ? value(ctx.conversations) : value; },
    flashStatus: noop, conversations: [],
    setTraceRuns: noop, setSelectedTraceId: noop,
    setSidebarOpen: noop, setBusy: noop, setStatusMessage: noop, refreshConversations: noop,
    createId: prefix => `${prefix}-${++id}`, createSystemMessage: content => ({ content }), toChatMessage: item => item,
    conversationId: "review-chat", messages: [], loading: false,
    setConversationId(value) { ctx.conversationId = value; },
    setConversationLoading(value) { ctx.loading = value; },
    setMessages(value) { ctx.messages = typeof value === "function" ? value(ctx.messages) : value; }
  };
  const functions = new Function("ctx", `with(ctx) { ${js}; return {${names.join(",")}}; }`)(ctx);
  return { ctx, ...functions };
}

test("clicking an older pending result submits that result's review ID", async () => {
  const { ctx, handleValidation } = harness();
  ctx.messages = [
    { id: "older", requiresValidation: true, validationId: "review-old" },
    { id: "newer", requiresValidation: true, validationId: "review-new" }
  ];
  let submitted;
  ctx.validateMedicalOutput = async (_choice, _comments, id) => {
    submitted = id;
    return { status: "validated", response: "confirmed" };
  };
  await handleValidation("older", "yes", "");
  assert.equal(submitted, "review-old");
  assert.equal(ctx.messages.find(item => item.id === "older").requiresValidation, false);
  assert.equal(ctx.messages.find(item => item.id === "newer").requiresValidation, true);
});

test("an out-of-order history response cannot overwrite the selected conversation", async () => {
  const { ctx, handleSelectConversation } = harness();
  const responses = { A: deferred(), B: deferred() };
  const signals = {};
  ctx.getConversationMessages = (id, signal) => { signals[id] = signal; return responses[id].promise; };
  const a = handleSelectConversation("A");
  const b = handleSelectConversation("B");
  assert.equal(signals.A.aborted, true);
  responses.B.resolve([{ content: "B history" }]);
  await b;
  responses.A.resolve([{ content: "A history" }]);
  await a;
  assert.equal(ctx.conversationId, "B");
  assert.deepEqual(ctx.messages.map(item => item.content), ["B history"]);
  assert.equal(ctx.loading, false);
});

test("an error from the previous history request cannot replace current messages", async () => {
  const { ctx, handleSelectConversation } = harness();
  const responses = { A: deferred(), B: deferred() };
  ctx.getConversationMessages = id => responses[id].promise;
  const a = handleSelectConversation("A");
  const b = handleSelectConversation("B");
  responses.B.resolve([{ content: "B history" }]);
  await b;
  responses.A.reject(new Error("late failure"));
  await a;
  assert.deepEqual(ctx.messages.map(item => item.content), ["B history"]);
});

test("starting a new conversation invalidates an outstanding history request", async () => {
  const { ctx, handleSelectConversation, handleNewConversation } = harness();
  const response = deferred();
  ctx.getConversationMessages = () => response.promise;
  const loading = handleSelectConversation("A");
  handleNewConversation();
  response.resolve([{ content: "old history" }]);
  await loading;
  assert.equal(ctx.conversationId, undefined);
  assert.deepEqual(ctx.messages, []);
  assert.equal(ctx.loading, false);
});

test("a review response cannot add messages after switching conversations", async () => {
  const { ctx, handleValidation, handleSelectConversation } = harness();
  ctx.messages = [{ id: "older", requiresValidation: true, validationId: "review-old" }];
  const response = deferred();
  ctx.validateMedicalOutput = () => response.promise;
  const validating = handleValidation("older", "yes", "");
  ctx.getConversationMessages = async () => [{ content: "B history" }];
  await handleSelectConversation("B");
  response.resolve({ status: "validated", response: "old confirmation" });
  await validating;
  assert.deepEqual(ctx.messages.map(item => item.content), ["B history"]);
  assert.equal(ctx.pendingValidationsRef.current.size, 0);
});

test("duplicate clicks submit once and display the authoritative server status", async () => {
  const { ctx, handleValidation } = harness();
  ctx.messages = [{ id: "older", requiresValidation: true, validationId: "review-old" }];
  const response = deferred();
  let calls = 0;
  ctx.validateMedicalOutput = () => { calls++; return response.promise; };
  const first = handleValidation("older", "yes", "");
  await handleValidation("older", "yes", "");
  response.resolve({ status: "rejected", response: "already rejected" });
  await first;
  assert.equal(calls, 1);
  const reviews = ctx.messages.filter(item => item.agent === "HUMAN_VALIDATED");
  assert.equal(reviews.length, 1);
  assert.equal(reviews[0].statusLabel, "需复查");
});

test("logout clears private drafts before another account signs in", async () => {
  const { ctx, handleLogout, handleAuth } = harness();
  ctx.inputValue = "account A private text";
  ctx.imageDraft = { file: { name: "account-A-scan.png" } };
  ctx.logoutLocal = async () => {};
  ctx.loginLocal = async () => ({ user_id: "account-B" });
  await handleLogout();
  await handleAuth("login", "account-B", "password");
  assert.equal(ctx.currentUser, "account-B");
  assert.equal(ctx.inputValue, "");
  assert.equal(ctx.imageDraft, null);
});

test("a late deletion cannot reset the conversation opened while it was pending", async () => {
  const { ctx, handleDeleteConversation, handleSelectConversation } = harness();
  ctx.conversationId = "A";
  const response = deferred();
  ctx.deleteConversation = () => response.promise;
  const deleting = handleDeleteConversation("A");
  ctx.getConversationMessages = async () => [{ content: "B history" }];
  await handleSelectConversation("B");
  response.resolve();
  await deleting;
  assert.equal(ctx.conversationId, "B");
  assert.deepEqual(ctx.messages.map(item => item.content), ["B history"]);
});

test("history restores only reviews the server marks pending with a valid ID", () => {
  const { toChatMessage } = harness();
  const stored = { message_id: 1, role: "assistant", content: "analysis", has_image: false,
    validation_id: "review-old", requires_validation: true };
  assert.equal(toChatMessage(stored).requiresValidation, true);
  assert.equal(toChatMessage(stored).validationId, "review-old");
  assert.equal(toChatMessage({ ...stored, requires_validation: false }).requiresValidation, false);
  assert.equal(toChatMessage({ ...stored, validation_id: null }).requiresValidation, false);
});
