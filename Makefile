start:
	python app/server.py
	#langchain app serve

ingest:
	python app/ingest.py

ingest-weaviate:
	python app/ingest-weaviate.py

ingest-faiss:
	python app/ingest-faiss.py
