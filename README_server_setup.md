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

Make sure that the user `flask` can write to the destination with:
```bash
sudo chown flask:flask /var/log/gunicorn/
```

Apply the changes and restart the service:
```bash
sudo systemctl daemon-reload
sudo systemctl restart gunicorn
```

## Testing

1. Stop the service: `sudo systemctl stop gunicorn`
2. Activate the virtual environment: `source ~/<app_name>/venv/bin/activate`
3. Run the app with either:
  a. With the internal server: `python ~/<app_name>/app_web/app.py`
  b. Via "gunicorn": `gunicorn --workers 1 --bind unix:/home/flask/gunicorn.socket --chdir /home/flask/<app_name>/app_web app:app`
4. When finished, start the service again: `sudo systemctl start gunicorn`
