FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 HF_HOME=/models
WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-rus tesseract-ocr-eng \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt constraints.txt ./
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir -r requirements.txt -c constraints.txt

ARG EMBEDDING_MODEL=intfloat/multilingual-e5-small
ARG EMBEDDING_REVISION=
ARG RERANKER_MODEL=cross-encoder/mmarco-mMiniLMv2-L12-H384-v1
ARG RERANKER_REVISION=
RUN EMB="${EMBEDDING_MODEL}" EMB_REV="${EMBEDDING_REVISION}" RR="${RERANKER_MODEL}" RR_REV="${RERANKER_REVISION}" \
    python -c "import os; from sentence_transformers import SentenceTransformer as S, CrossEncoder as C; \
S(os.environ['EMB'], revision=os.environ['EMB_REV'] or None); C(os.environ['RR'], revision=os.environ['RR_REV'] or None)"

COPY app app
RUN useradd --create-home app && chown -R app /app /models
USER app
ENV HF_HUB_OFFLINE=1 \
    EMBEDDING_MODEL=${EMBEDDING_MODEL} \
    EMBEDDING_REVISION=${EMBEDDING_REVISION} \
    RERANKER_MODEL=${RERANKER_MODEL} \
    RERANKER_REVISION=${RERANKER_REVISION} \
    LOG_FORMAT=json
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips=*", "--no-access-log"]
