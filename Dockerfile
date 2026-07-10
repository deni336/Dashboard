FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/kasugai/logs /app/kasugai/resources /root/Kasugai \
    && printf "[Application]\nbuttons =\n\n[WebServer]\nport = 8000\naddress = 0.0.0.0\nkasaddress = host.docker.internal\nkasport = 8008\nmediaport = 50052\n\n[Logging]\npath = kasugai/logs/\nloglevel = INFO\n\n[FileTransfer]\nuploadfolder = kasugai/resources/\naddress = host.docker.internal\nport = 50051\n\n[Database]\ndbpath = chat_history.db\nencryption_key =\n" > /root/Kasugai/config.ini

EXPOSE 8000

CMD ["waitress-serve", "--host=0.0.0.0", "--port=8000", "src.wsgi:app"]
