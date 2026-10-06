FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY templates/ templates/

RUN useradd --system --no-create-home appuser
USER appuser

EXPOSE 3100

CMD ["python", "main.py"]
