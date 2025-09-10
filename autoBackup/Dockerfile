FROM reg.reaweb.uk/cron 
# https://github.com/jwansek/cron/

RUN git clone https://github.com/monitorjbl/api_client.git /api_client && cd /api_client && python3 setup.py install && rm -rf /api_client
COPY . /app
WORKDIR /app
RUN pip3 install -r requirements.txt
RUN pip3 install -r TasmotaCLI/requirements.txt

RUN echo "0 21 * * sat,wed root python3 /app/autoBackup.py > /proc/1/fd/1 2>/proc/1/fd/2" > /etc/crontab
RUN echo "@monthly root python3 /app/autoScrub.py > /proc/1/fd/1 2>/proc/1/fd/2" >> /etc/crontab
ENTRYPOINT ["bash"]
CMD ["entrypoint.sh"]
