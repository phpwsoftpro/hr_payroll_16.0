FROM odoo:16.0

USER root
RUN apt-get update && apt-get install -y python3-pip
RUN pip3 install pandas

USER odoo
