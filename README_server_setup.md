# Droplet setup

## Install Flask droplet template from DigitalOcean

- https://marketplace.digitalocean.com/apps/flask#getting-started

## Add `flask` user to sudo group

```bash
usermod -aG sudo flask
```

## Get the repo

- On the VM, create a new SSH key: `ssh-keygen -t rsa -b 4096 -C "<email_address>"`
- Add the key to the ssh-agent: `eval "$(ssh-agent -s)"` and `ssh-add ~/.ssh/id_rsa`.
- Copy the public key with `cat ~/.ssh/id_rsa.pub` and add it to your GitHub account, possibly as a "deploy key" for the repo alone.
- Clone the repo using the SSH URL

## Configure for launch

### Create a virtual environment for the project:
```bash
python3 -m venv ~/<app_name>/venv
```

### Activate the virtual environment and install dependencies:
```bash
source ~/<app_name>/venv/bin/activate
pip install -r ~/<app_name>/app_web/requirements.txt
pip install gunicorn gevent
```

### Edit `/etc/systemd/system/gunicorn.service`

From root, change `/etc/systemd/system/gunicorn.service` as follows:
```bash
WorkingDirectory=/home/flask/<app_name>/app_web
ExecStart=/home/flask/<app_name>/venv/bin/gunicorn --workers 1 --worker-class gevent --bind unix:/home/flask/gunicorn.socket --chdir /home/flask/<app_name>/app_web app:app
```
> NOTE: because we are using `gevent`, it's suggested to use only 1 worker.

If you wish to keep an error log, change as follows:
```bash
ExecStart=/home/flask/<app_name>/venv/bin/gunicorn --workers 1 --worker-class gevent --bind unix:/home/flask/gunicorn.socket --chdir /home/flask/<app_name>/app_web app:app --error-logfile /var/log/gunicorn/error.log
```

For a more detailed log, add the following to the `[Service]` section:
```bash
StandardOutput=append:/var/log/gunicorn/stdout.log
StandardError=append:/var/log/gunicorn/stderr.log
```

Make sure that the user `flask` can write to the destination with:
```bash
sudo mkdir -p /var/log/gunicorn
sudo chown flask:flask /var/log/gunicorn/
```

Apply the changes and restart the service:
```bash
sudo systemctl daemon-reload && sudo systemctl restart gunicorn
```

### Setup domain a name

Source [How To Serve Flask Applications with Gunicorn and Nginx on Ubuntu 20.04](https://www.digitalocean.com/community/tutorials/how-to-serve-flask-applications-with-gunicorn-and-nginx-on-ubuntu-20-04)

Create a new server block configuration file for your domain:

`sudo vim /etc/nginx/sites-available/my.site.com`

In the server block, add the following configuration:

```nginx
server {
    listen 80;
    server_name my.site.com;

    client_max_body_size 4G;
    keepalive_timeout 5;

    location / {
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header Host $host;
        proxy_redirect off;
        proxy_buffering off;
        proxy_pass http://unix:/home/flask/gunicorn.socket;
    }
}
```

Enable the Nginx server block configuration by linking the file to the sites-enabled directory:

```bash
sudo ln -s /etc/nginx/sites-available/my.site.com /etc/nginx/sites-enabled
```

Test for syntax errors: `sudo nginx -t`

If there are no errors, restart the Nginx service: `sudo systemctl restart nginx`
At this point, your Flask app should be accessible via your domain name (`my.site.com`).

### Add HTTPS support

Source [How To Serve Flask Applications with Gunicorn and Nginx on Ubuntu 20.04](https://www.digitalocean.com/community/tutorials/how-to-serve-flask-applications-with-gunicorn-and-nginx-on-ubuntu-20-04)

To add HTTPS support, use Certbot to obtain an SSL certificate from Let's Encrypt:

- Install Certbot's Nginx package: `sudo apt install python3-certbot-nginx`
- Run Certbot to obtain and configure the SSL certificate: `sudo certbot --nginx -d my.site.com`
- Follow the prompts to provide your email address, agree to the terms of service, and choose whether to redirect HTTP traffic to HTTPS.
- Certbot will automatically configure Nginx and reload the configuration.
- After completing these steps, the Flask app should be accessible via HTTPS using the domain name (`https://my.site.com`).


## Testing

1. Stop the service: `sudo systemctl stop gunicorn`
2. Activate the virtual environment: `source ~/<app_name>/venv/bin/activate`
3. Run the app with either:
  a. With the internal server: `python ~/<app_name>/app_web/app.py`
  b. Via "gunicorn": `gunicorn --workers 1 --bind unix:/home/flask/gunicorn.socket --chdir /home/flask/<app_name>/app_web app:app`
4. When finished, start the service again: `sudo systemctl start gunicorn`
