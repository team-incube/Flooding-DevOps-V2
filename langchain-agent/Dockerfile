FROM python:3.12-slim

WORKDIR /app

RUN addgroup --gid 1000 appuser && \
    adduser --uid 1000 --gid 1000 --disabled-password --gecos "" appuser

# Install helm (needed for helm_tool.py subprocess calls)
RUN apt-get update && apt-get install -y curl && \
    curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chown -R appuser:appuser /app
USER 1000

EXPOSE 8080

CMD ["python", "main.py"]
