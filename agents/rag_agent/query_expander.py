import logging
import re
from typing import List, Dict, Any

class QueryExpander:
    """
    Expands user queries with medical terminology to improve retrieval.
    """
    def __init__(self, config):
        self.logger = logging.getLogger(f"{self.__module__}")
        self.config = config
        self.model = config.rag.llm

    def should_expand(self, query: str) -> tuple[bool, str]:
        """Choose cheap deterministic expansion bypasses for clear questions."""
        if not self.config.rag.query_expansion_enabled:
            return False, "disabled"
        if not self.config.rag.skip_simple_query_expansion:
            return True, "always_expand"

        normalized = " ".join(query.strip().split())
        if not normalized:
            return False, "empty_query"

        # Follow-ups and underspecified requests benefit from conversation-aware
        # terminology expansion. Keep this deliberately conservative.
        ambiguous_markers = (
            "这个", "那个", "上述", "前面", "刚才", "它", "他们", "怎么办",
            "this", "that", "these", "those", "it ", "they", "above", "previous",
        )
        lowered = normalized.lower()
        if any(marker in lowered for marker in ambiguous_markers):
            return True, "context_dependent"

        sentence_count = len([part for part in re.split(r"[。！？.!?]+", normalized) if part.strip()])
        if len(normalized) <= self.config.rag.simple_query_max_chars and sentence_count <= 1:
            return False, "simple_clear_query"
        return True, "complex_query"
        
    def expand_query(self, original_query: str) -> Dict[str, Any]:
        """
        Expand the original query with relevant medical terms.
        
        Args:
            original_query: The user's original query
            
        Returns:
            Dictionary with original and expanded queries
        """
        self.logger.info(f"Expanding query: {original_query}")
        
        should_expand, reason = self.should_expand(original_query)
        if not should_expand:
            return {
                "original_query": original_query,
                "expanded_query": original_query,
                "expansion_skipped": True,
                "expansion_reason": reason,
            }

        # Generate expansions - implement one of the strategies below
        expanded_query = self._generate_expansions(original_query)
        
        return {
            "original_query": original_query,
            "expanded_query": expanded_query.content,
            "expansion_skipped": False,
            "expansion_reason": reason,
        }
    
    def _generate_expansions(self, query: str) -> str:
        """Use LLM to expand query with medical terminology."""
        prompt = f"""
        As a medical expert, expand the following query with relevant medical terminology, 
        synonyms, and related concepts that would help in retrieving relevant medical information:
        
        User Query: {query}
        
        Expand the query only if you feel like it is required, otherwise keep the user query intact.
        Be specific to the medical or any other domain mentioned in the ueer query, do not add other medical domains.
        If the user query asks about answering in tabular format, include that in the expanded query and do not answer in tabular format yourself.
        Provide only the expanded query without explanations.
        """
        expansion = self.model.invoke(prompt)
        
        return expansion
