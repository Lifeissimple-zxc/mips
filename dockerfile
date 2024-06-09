FROM python:3.9

# Installing a text editor JIC
ENV USE_POLLING_FILE_WATCHER=true
RUN apt-get update && apt-get install nano

# Set working dir of the container
WORKDIR /app

# Copy current directory contents to /app
COPY . /app

RUN pip install -r requirements.txt

CMD ["bash", "execute.sh"]
