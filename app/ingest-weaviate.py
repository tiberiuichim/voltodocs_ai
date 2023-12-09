from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
import logging
import os

import click
from langchain.docstore.document import Document
from langchain.embeddings import HuggingFaceInstructEmbeddings
from langchain.text_splitter import Language, RecursiveCharacterTextSplitter
from langchain.vectorstores import Weaviate
import torch

from constants import (
    DOCUMENT_MAP,
    EMBEDDING_MODEL_NAME,
    INGEST_THREADS,
    SOURCE_DIRECTORY,
    WEAVIATE_URL,
)


def file_log(logentry):
    file1 = open("file_ingest.log", "a")
    file1.write(logentry + "\n")
    file1.close()
    print(logentry + "\n")


def load_single_document(file_path: str) -> Document | None:
    # Loads a single document from a file path
    try:
        file_extension = os.path.splitext(file_path)[1]
        loader_class = DOCUMENT_MAP.get(file_extension)
        if loader_class:
            file_log(file_path + " loaded.")
            loader = loader_class(file_path)
        else:
            file_log(file_path + " document type is undefined.")
            raise ValueError("Document type is undefined")
        return loader.load()[0]
    except Exception as ex:
        file_log("%s loading error: \n%s" % (file_path, ex))
        return None


def load_document_batch(filepaths):
    logging.info("Loading document batch")
    # create a thread pool
    with ThreadPoolExecutor(len(filepaths)) as exe:
        # load files
        futures = [exe.submit(load_single_document, name)
                   for name in filepaths]
        # collect data
        if futures is None:
            file_log("Some files failed to submit")
            return None
        else:
            data_list = [future.result() for future in futures]
            # return data and file paths
            return (data_list, filepaths)


def load_documents(source_dir: str) -> list[Document]:
    # Loads all documents from the source documents directory,
    # including nested folders

    paths = []
    for root, _, files in os.walk(source_dir):
        for file_name in files:
            print("Importing: " + file_name)
            file_extension = os.path.splitext(file_name)[1]
            source_file_path = os.path.join(root, file_name)
            if file_extension in DOCUMENT_MAP.keys():
                paths.append(source_file_path)

    # Have at least one worker and at most INGEST_THREADS workers
    n_workers = min(INGEST_THREADS, max(len(paths), 1))
    chunksize = round(len(paths) / n_workers) or 1
    docs = []
    with ProcessPoolExecutor(n_workers) as executor:
        futures = []
        # split the load operations into chunks
        for i in range(0, len(paths), chunksize):
            # select a chunk of filenames
            filepaths = paths[i: (i + chunksize)]
            # submit the task
            try:
                future = executor.submit(load_document_batch, filepaths)
            except Exception as ex:
                file_log("executor task failed: %s" % (ex))
                future = None
            if future is not None:
                futures.append(future)
        # process all results
        for future in as_completed(futures):
            # open the file and load the data
            try:
                contents, _ = future.result()
                docs.extend(contents)
            except Exception as ex:
                file_log("Exception: %s" % (ex))

    return docs


text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000, chunk_overlap=200)
python_splitter = RecursiveCharacterTextSplitter.from_language(
    language=Language.PYTHON, chunk_size=880, chunk_overlap=200
)
ts_splitter = RecursiveCharacterTextSplitter.from_language(
    language=Language.TS, chunk_size=880, chunk_overlap=200
)
js_splitter = RecursiveCharacterTextSplitter.from_language(
    language=Language.JS, chunk_size=880, chunk_overlap=200
)

extension_handlers = {
    ".md": text_splitter,
    ".txt": text_splitter,
    ".py": python_splitter,
    ".ts": ts_splitter,
    ".tsx": ts_splitter,
    ".js": js_splitter,
    ".jsx": js_splitter,
}


def split_documents(documents: list[Document]) -> list[Document]:
    # Splits documents for correct Text Splitter
    docs = defaultdict(list)

    for doc in documents:
        if doc is not None:
            file_extension = os.path.splitext(doc.metadata["source"])[1]
            if file_extension not in extension_handlers:
                file_extension = ".txt"

            docs[file_extension].append(doc)

    texts = []
    for ext, ext_docs in docs.items():
        splitter = extension_handlers[ext]
        texts.extend(splitter.split_documents(ext_docs))

    return texts


@click.command()
@click.option(
    "--device_type",
    default="cuda" if torch.cuda.is_available() else "cpu",
    type=click.Choice(
        [
            "cpu",
            "cuda",
            "ipu",
            "xpu",
            "mkldnn",
            "opengl",
            "opencl",
            "ideep",
            "hip",
            "ve",
            "fpga",
            "ort",
            "xla",
            "lazy",
            "vulkan",
            "mps",
            "meta",
            "hpu",
            "mtia",
        ],
    ),
    help="Device to run on. (Default is cuda)",
)
def main(device_type):
    # Load documents and split in chunks
    logging.info(f"Loading documents from {SOURCE_DIRECTORY}")
    documents = load_documents(SOURCE_DIRECTORY)

    texts = split_documents(documents)

    logging.info(f"Loaded {len(documents)} documents from {SOURCE_DIRECTORY}")
    logging.info(f"Split into {len(texts)} chunks of text")

    embeddings = HuggingFaceInstructEmbeddings(
        model_name=EMBEDDING_MODEL_NAME,
        model_kwargs={"device": device_type},
    )

    if texts:
        db = Weaviate.from_documents(
            texts,
            embeddings,
            weaviate_url=WEAVIATE_URL,
        )
        query = "What is Volto?"
        docs = db.similarity_search(query)
        assert len(docs) > 0
    else:
        logging.warning("No documents found to be indexed")


if __name__ == "__main__":
    logging.basicConfig(
        format="%(asctime)s - %(levelname)s - %(filename)s:%(lineno)s - %(message)s",
        level=logging.INFO,
    )
    main()
