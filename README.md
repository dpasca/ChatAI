# ChatAI

A basic AI chatbot based on OpenAI, currently using the Assistant API (beta).

The web app is based on _Flask_. It's been tested to run on DigitalOcean App platform.

This application is developed mainly by [Davide Pasca](https://github.com/dpasca).
See commits for other contributors.

## Features

- AI chatbot based on OpenAI and Assistant API (beta)
- Sense of time and location using prompt injection
- Image generation and storage
- Support for PDF knowledge files (need to upload manually to OpenAI assistant settings)
- Code syntax highlighting and LaTeX rendering

## Requirements

See `requirements.txt` for Python dependencies.

### Environment variables

- `OPENAI_API_KEY` is the API key for OpenAI.
- `CHATAI_FLASK_SECRET_KEY` is the secret key for Flask.
- `DO_SPACES_ACCESS_KEY` is the access key for DigitalOcean Spaces.
- `DO_SPACES_SECRET_KEY` is the secret key for DigitalOcean Spaces.
- `DO_STORAGE_CONTAINER` is the name of the container in DigitalOcean Spaces (e.g. `myai_spaces`).
- `DO_STORAGE_SERVER` is the URL of the DigitalOcean Spaces server (e.g. `https://myai.sfo.digitaloceanspaces.com`).

## Installation 

### Local development

It's suggested to use a virtual environment for Python.

Install _Flask_.

Install the dependencies with `pip install -r requirements.txt`.

Create a `.env` file in the root directory with the following variables:

```
OPENAI_API_KEY=********
CHATAI_FLASK_SECRET_KEY=********
DO_SPACES_ACCESS_KEY=********
DO_SPACES_SECRET_KEY=********
DO_STORAGE_CONTAINER=********
DO_STORAGE_SERVER=https://********
```

### Production

This is an example in the case of DigitalOcean. Change the steps as needed if you'll be using a different provider, or your own server.

1. Created a dedicated Project in DigitalOcean, if required.
2. Create an App under the Project.
3. The first step of the app creation will ask where to get the code from. You should select this GitHub repository.
4. Set the required environment variables in the app (to update them later, go to *Manage -> Apps -> Your app name -> Settings -> App-Level Environment Variables*).

## Usage 

### Local development

```
cd app
flask --debug run --host=0.0.0.0 --port=8080
```

The app will be available locally at `http://127.0.0.1:8080`.

### Production

The app will be available globally at `https://yourappname.ondigitalocean.app`.

## License

This is total freeware at the moment.
