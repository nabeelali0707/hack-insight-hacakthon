# BijliCast - Hugging Face Space (Docker SDK). Serves the dashboard on port 7860 and refreshes
# the pipeline hourly inside the container.
FROM python:3.12-slim

RUN useradd -m -u 1000 user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONPATH=/home/user/app/src \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/home/user/.cache/huggingface \
    TZ=UTC
WORKDIR /home/user/app

# CPU-only torch first (the default Linux wheel pulls ~2 GB of CUDA libraries)
COPY --chown=user requirements-space.txt .
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r requirements-space.txt

USER user
# bake the multilingual embedding model into the image (no download at cold start)
RUN python -c "from sentence_transformers import SentenceTransformer as S; S('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')"

COPY --chown=user . .
EXPOSE 7860
CMD ["bash", "start.sh"]
