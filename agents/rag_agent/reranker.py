import os
import re
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Union

import requests

class Reranker:
    """
    Reranks retrieved documents using a remote reranker model served over an
    OpenAI-compatible ``/rerank`` endpoint.
    """
    def __init__(self, config):
        """
        Initialize the reranker with configuration.

        Args:
            config: Configuration object containing reranker settings
        """
        self.logger = logging.getLogger(__name__)

        self.model_name = config.rag.reranker_model
        self.api_base = config.rag.reranker_api_base.rstrip("/")
        self.api_key = config.rag.reranker_api_key
        self.timeout = config.rag.reranker_timeout
        self.endpoint = f"{self.api_base}/rerank"
        self.top_k = config.rag.reranker_top_k
        # The reranker model has a hard context limit (8192 tokens). Documents
        # are truncated before scoring so one oversized chunk cannot 400 the
        # whole batch — relevance is judged on the leading text anyway.
        self.max_doc_chars = config.rag.reranker_max_doc_chars
        self.logger.info(f"Using remote reranker model: {self.model_name} at {self.endpoint}")

    def _score(self, query: str, texts: List[str]) -> List[float]:
        """
        Call the remote rerank endpoint and return one score per input text,
        in the original input order.
        """
        truncated = [t[:self.max_doc_chars] for t in texts]
        response = requests.post(
            self.endpoint,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model_name,
                "query": query,
                "documents": truncated,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()

        # The endpoint may return results in relevance order, so map them back
        # onto the original positions via the "index" field.
        scores = [0.0] * len(texts)
        for item in payload.get("results", []):
            idx = item.get("index")
            if idx is not None and 0 <= idx < len(scores):
                scores[idx] = float(item.get("relevance_score", 0.0))
        return scores

    def rerank(self, query: str, documents: Union[List[Dict[str, Any]], List[str]], parsed_content_dir: str) -> List[Dict[str, Any]]:
        """
        Rerank documents based on query relevance using the remote reranker.

        Args:
            query: User query
            documents: Either a list of documents (dictionaries) or a list of strings

        Returns:
            Reranked list of documents with updated scores
        """
        try:
            if not documents:
                return [], []

            # Handle different document formats and ensure consistent structure
            if documents:
                # if the retrieved documents is just a list of strings, we add a default score
                if isinstance(documents[0], str):
                    # Convert simple strings to dictionaries
                    docs_list = []
                    for i, doc_text in enumerate(documents):
                        docs_list.append({
                            "id": i,
                            "content": doc_text,
                            "score": 1.0  # Default score
                        })
                    documents = docs_list
                # if the retrieved documents is a list of dictionaries, we use the original score
                elif isinstance(documents[0], dict):
                    # Ensure all required fields exist in dictionaries
                    for i, doc in enumerate(documents):
                        # Ensure ID exists
                        if "id" not in doc:
                            doc["id"] = i
                        # Ensure score exists
                        if "score" not in doc:
                            doc["score"] = 1.0
                        # Ensure content exists (unlikely to be missing but just in case)
                        if "content" not in doc:
                            if "text" in doc:  # Some implementations might use "text" instead
                                doc["content"] = doc["text"]
                            else:
                                doc["content"] = f"Document {i}"

            # Get relevance scores from the remote reranker
            scores = self._score(query, [doc["content"] for doc in documents])

            # Add scores to documents
            for i, score in enumerate(scores):
                documents[i]["rerank_score"] = float(score)  # Store the new score from reranking
                # If the original document didn't have a score, use the rerank score
                if "score" not in documents[i]:
                    documents[i]["score"] = 1.0
                # Combine (average) the original score and rerank score
                documents[i]["combined_score"] = (documents[i]["score"] + float(score)) / 2

            # Sort by combined score
            reranked_docs = sorted(documents, key=lambda x: x["combined_score"], reverse=True)

            # Limit to top_k if needed
            if self.top_k and len(reranked_docs) > self.top_k:
                reranked_docs = reranked_docs[:self.top_k]

            # Extract picture references
            picture_reference_paths = []
            for doc in reranked_docs:
                matches = re.finditer(r"picture_counter_(\d+)", doc["content"])
                for match in matches:
                    counter_value = int(match.group(1))
                    # Create picture path based on document source and counter
                    doc_basename = os.path.splitext(doc['source'])[0]  # Remove file extension
                    # picture_path = Path(os.path.abspath(parsed_content_dir + "/" + f"{doc_basename}-picture-{counter_value}.png")).as_uri()
                    picture_path = os.path.join("http://localhost:8000/", parsed_content_dir + "/" + f"{doc_basename}-picture-{counter_value}.png")
                    picture_reference_paths.append(picture_path)

            return reranked_docs, picture_reference_paths

        except Exception as e:
            self.logger.error(f"Error during reranking: {e}")
            # Fallback to original ranking if reranking fails
            self.logger.warning("Falling back to original ranking")
            return documents, []