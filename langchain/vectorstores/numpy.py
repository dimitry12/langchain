"""Wrapper around numpy vector database."""
from __future__ import annotations

import uuid
from typing import Any, Callable, Dict, Iterable, List, Optional

import numpy as np

from langchain.docstore.base import AddableMixin, Docstore
from langchain.docstore.document import Document
from langchain.docstore.in_memory import InMemoryDocstore
from langchain.embeddings.base import Embeddings
from langchain.vectorstores.base import VectorStore
from langchain.vectorstores.utils import maximal_marginal_relevance


class NumpyVectorStore(VectorStore):
    """Wrapper around numpy vector database.

    To use, you need nothing other than numpy making it a good choice for quick prototyping in fresh environments.

    Example:
        .. code-block:: python

            from langchain import NumpyVectorStore
            np_vector_store = NumpyVectorStore(embedding_function, docstore)

    """

    def __init__(
        self,
        embedding_function: Callable,
        index: Any,
        docstore: Docstore,
        index_to_docstore_id: Dict[int, str],
    ):
        """Initialize with necessary components."""
        self.embedding_function = embedding_function
        self.index = index
        self.docstore = docstore
        self.index_to_docstore_id = index_to_docstore_id

    def add_texts(
        self, texts: Iterable[str], metadatas: Optional[List[dict]] = None
    ) -> List[str]:
        """Run more texts through the embeddings and add to the vectorstore.

        Args:
            texts: Iterable of strings to add to the vectorstore.
            metadatas: Optional list of metadatas associated with the texts.

        Returns:
            List of ids from adding the texts into the vectorstore.
        """
        if not isinstance(self.docstore, AddableMixin):
            raise ValueError(
                "If trying to add texts, the underlying docstore should support "
                f"adding items, which {self.docstore} does not"
            )
        # Embed and create the documents.
        embeddings = [self.embedding_function(text) for text in texts]
        documents = []
        for i, text in enumerate(texts):
            metadata = metadatas[i] if metadatas else {}
            documents.append(Document(page_content=text, metadata=metadata))
        # Add to the index, the index_to_id mapping, and the docstore.
        starting_len = len(self.index_to_docstore_id)
        self.index = np.vstack((self.index, np.array(embeddings, dtype=np.float32)))
        # Get list of index, id, and docs.
        full_info = [
            (starting_len + i, str(uuid.uuid4()), doc)
            for i, doc in enumerate(documents)
        ]
        # Add information to docstore and index.
        self.docstore.add({_id: doc for _, _id, doc in full_info})
        index_to_id = {index: _id for index, _id, _ in full_info}
        self.index_to_docstore_id.update(index_to_id)
        return [_id for _, _id, _ in full_info]

    def similarity_search(self, query: str, k: int = 4) -> List[Document]:
        """Return docs most similar to query.

        Args:
            query: Text to look up documents similar to.
            k: Number of Documents to return. Defaults to 4.

        Returns:
            List of Documents most similar to the query.
        """
        embedding = self.embedding_function(query)

        D = np.sum((self.index - np.array(embedding, dtype=np.float32)) ** 2, axis=1)
        I = np.argsort(D)
        indices = I[:k] if len(I) >= k else np.pad(I, (0, k - len(I)), "constant", constant_values=-1)

        docs = []
        for i in indices:
            if i == -1:
                # This happens when not enough docs are returned.
                continue
            _id = self.index_to_docstore_id[i]
            doc = self.docstore.search(_id)
            if not isinstance(doc, Document):
                raise ValueError(f"Could not find document for id {_id}, got {doc}")
            docs.append(doc)
        return docs

    def max_marginal_relevance_search(
        self, query: str, k: int = 4, fetch_k: int = 20
    ) -> List[Document]:
        """Return docs selected using the maximal marginal relevance.

        Maximal marginal relevance optimizes for similarity to query AND diversity
        among selected documents.

        Args:
            query: Text to look up documents similar to.
            k: Number of Documents to return. Defaults to 4.
            fetch_k: Number of Documents to fetch to pass to MMR algorithm.

        Returns:
            List of Documents selected by maximal marginal relevance.
        """
        embedding = self.embedding_function(query)
        _, indices = self.index.search(np.array([embedding], dtype=np.float32), fetch_k)
        # -1 happens when not enough docs are returned.
        embeddings = [self.index.reconstruct(int(i)) for i in indices[0] if i != -1]
        mmr_selected = maximal_marginal_relevance(embedding, embeddings, k=k)
        selected_indices = [indices[0][i] for i in mmr_selected]
        docs = []
        for i in selected_indices:
            _id = self.index_to_docstore_id[i]
            doc = self.docstore.search(_id)
            if not isinstance(doc, Document):
                raise ValueError(f"Could not find document for id {_id}, got {doc}")
            docs.append(doc)
        return docs

    @classmethod
    def from_texts(
        cls,
        texts: List[str],
        embedding: Embeddings,
        metadatas: Optional[List[dict]] = None,
        **kwargs: Any,
    ) -> NumpyVectorStore:
        """Construct NumpyVectorStore wrapper from raw documents.

        This is a user friendly interface that:
            1. Embeds documents.
            2. Creates an in memory docstore
            3. Initializes the numpy-based vectorstore

        This is intended to be a quick way to get started.

        Example:
            .. code-block:: python

                from langchain import NumpyVectorStore
                from langchain.embeddings import OpenAIEmbeddings
                embeddings = OpenAIEmbeddings()
                np_vectorstore = NumpyVectorStore.from_texts(texts, embeddings)
        """
        index = np.array(embedding.embed_documents(texts), dtype=np.float32)
        documents = []
        for i, text in enumerate(texts):
            metadata = metadatas[i] if metadatas else {}
            documents.append(Document(page_content=text, metadata=metadata))
        # `str(i)` instead of `str(uuid.uuid4())` for ease of unit-testing
        index_to_id = {i: str(i) for i in range(len(documents))}
        docstore = InMemoryDocstore(
            {index_to_id[i]: doc for i, doc in enumerate(documents)}
        )
        return cls(embedding.embed_query, index, docstore, index_to_id)

"""
docsearch = NumpyVectorStore.from_texts(['one', 'two', 'three', 'red', 'green', 'blue'], base_embeddings)
docsearch.similarity_search("red", k=3)
docsearch.similarity_search("three", k=3)
docsearch.similarity_search("rose", k=3)
docsearch.similarity_search("three roses", k=3)
docsearch.similarity_search("three red roses", k=3)
"""