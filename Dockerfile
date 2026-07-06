FROM python:3.11-slim

WORKDIR /code

# Install system deps for pypdfium2
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-hf.txt .
RUN pip install --no-cache-dir -r requirements-hf.txt

COPY app.py calc.py pricing.json prompt_v4.txt chat.html pricing.html ./
COPY .env.example ./

EXPOSE 7860
CMD ["sh", "-c", "exec python app.py"]
