FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# O banco AIRAC (173 MB) fica fora da imagem e do git; monte-o como volume:
#   docker run -p 8000:8000 --env-file .env \
#     -v ./core_aero/data/airac:/app/core_aero/data/airac dispatch-release
EXPOSE 8000

CMD ["gunicorn", "aero_saas.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2"]
