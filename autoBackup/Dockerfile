FROM ubuntu:20.04
ENV TZ=Europe/London
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone
RUN apt-get update -y
RUN apt-get install -y python3-pip iputils-ping cron 
COPY . /app
WORKDIR /app
RUN pip3 install -r requirements.txt
RUN pip3 install -r TasmotaCLI/requirements.txt

RUN echo "0 21 * * sat,wed root python3 /app/autoBackup.py > /proc/1/fd/1 2>/proc/1/fd/2" > /etc/crontab
ENTRYPOINT ["bash"]
CMD ["entrypoint.sh"]