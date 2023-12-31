import weaviate

from langchain.llms import LlamaCpp
from langchain.retrievers.weaviate_hybrid_search import WeaviateHybridSearchRetriever
from langchain.prompts import ChatPromptTemplate
from langchain.pydantic_v1 import BaseModel
from langchain.schema.output_parser import StrOutputParser
from langchain.schema.runnable import RunnableParallel, RunnablePassthrough
from langchain.vectorstores import FAISS
from langchain.embeddings import HuggingFaceInstructEmbeddings

from langchain.callbacks.manager import CallbackManager
from langchain.callbacks.streaming_stdout import StreamingStdOutCallbackHandler

# from langchain.chat_models import ChatOllama


class Question(BaseModel):
    __root__: str


def weaviate_retriever(constants):
    client = weaviate.Client(
        url=constants.WEAVIATE_URL,
    )
    retriever = WeaviateHybridSearchRetriever(
        client=client,
        index_name="LangChain",
        text_key="text",
        attributes=[],
        create_schema_if_missing=True,
    )
    return retriever


def faiss_retriever(EMBEDDING_MODEL_NAME):
    embeddings = HuggingFaceInstructEmbeddings(
        model_name=EMBEDDING_MODEL_NAME,
        model_kwargs={"device": "cuda"},
    )
    with open("DB/faiss.pickke", "rb") as f:
        bindata = f.read()

    db = FAISS.deserialize_from_bytes(bindata, embeddings)
    return db.as_retriever(
        search_type="mmr", search_kwargs={"k": 6, "lambda_mult": 0.8}
    )


def make_chain(
    constants,
):
    retriever = faiss_retriever(constants.EMBEDDING_MODEL_NAME)
    # Optionally, pull from the Hub
    # from langchain import hub
    # prompt = hub.pull("rlm/rag-prompt")
    template = """You are a helpful assistant that answers questions. You answer questions only based on the context information that is provided to you. Answer the following question:
    {question}

    Context information that will be used to answer the question:
    {context}
    """
    prompt = ChatPromptTemplate.from_template(template)

    # ollama_llm = "llama2:7b-chat"
    # ollama_llm = "yarn-mistral"  # 64k context size
    # yarn-mistral:7b-128k
    # model = ChatOllama(model=ollama_llm)

    model_path = (
        "/mnt/docker/work/sd/text-generation-webui/models/llama-2-7b.Q5_K_S.gguf"
    )
    # yarn-mistral-7b-64k.Q4_K_M.gguf"
    # model_path = "/mnt/docker/work/sd/text-generation-webui/models/NousResearch_Yarn-Mistral-7b-64k"
    # model_path = "/mnt/docker/work/sd/text-generation-webui/models/openassistant-llama2-13b-orca-8k-3319.Q4_K_M.gguf"
    # model_path = "TheBloke/Yarn-Mistral-7B-64k-GGUF"

    # Change this value based on your model and your GPU VRAM pool.
    n_gpu_layers = 33
    n_batch = (
        # Between 1 and n_ctx, consider the amount of VRAM in your GPU.
        512
    )
    callback_manager = CallbackManager([StreamingStdOutCallbackHandler()])

    # Make sure the model path is correct for your system!
    model = LlamaCpp(
        model_path=model_path,
        n_ctx=9000,
        n_gpu_layers=n_gpu_layers,
        n_batch=n_batch,
        callback_manager=callback_manager,
        verbose=True,  # Verbose is required to pass to the callback manager
    )

    # RAG chain
    runnable = RunnableParallel(
        {"context": retriever, "question": RunnablePassthrough()}
    )
    chain = runnable | prompt | model | StrOutputParser()

    chain = chain.with_types(input_type=Question)
    return chain
