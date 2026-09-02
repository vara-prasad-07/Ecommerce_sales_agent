FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# One image, two roles — the same image is deployed as two Azure Container
# Apps with different start commands (see README.md's Azure section):
#   worker:  python -m agent.main start
#   web:     uvicorn server.app:app --host 0.0.0.0 --port 8000
# This default CMD runs the web trigger; override it for the worker.
CMD ["uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8000"]
