This library provides an interface with the Kalshi exchange. There are strategies under the src/strategies folder

### SETUP

- Make sure you have python `3.11.2`
- Insteall virtual env with `pip3.11 install virtualenv`
- Create a directory for your venv `mkdir venv`
- `cd venv`
- Create a venv `python3.11 -m venv .`
- `cd ..`
- Activate the venv with `source venv/bin/activate`. From now on, you will need to activate the venv before development. You can add this command to your zsh/bash profile so you don't have to do it everytime you log in
- Install poetry with pipx. To install pipx do, `brew install pipx`, then do `pipx install poetry`
- Run `pipx ensurepath` to add it to your path
- Run `poetry install` to install the dependencies to your venv
- Set up some default formatters. I'd recommend black and isort. Also set up autoformat on save (https://stackoverflow.com/questions/59433286/vs-code-prettier-format-on-save-doesnt-work)

#### Credentials

To setup your credentials, export the three variables in your local environment:

- API_URL (example: https://demo-api.kalshi.co/trade-api)
- API_VERSION (example: v2)
- API_USERNAME
- API_PASSWORD

In order for tests to pass, you need these env vars. These vars are used for functioanl
tests (explained below) and some regular testing. You can automatically add these env vars
by creating a bash script like so:

```
#!/bin/sh

export API_URL='https://demo-api.kalshi.co/trade-api'
export API_VERSION='v2'
export API_USERNAME='your-email@email.com'
export API_PASSWORD='some-password'
```

And then adding the following to your bash / zsh profile: `source path/to /your/script.sh`

### DESIGN

All the soure code is under the `/src` folder. Under the `/exchange` repository,
we have our interface with the exchange. This helps us keep track of information
locally vs on the exchange. We put all of our strategies under the strategies folder.

### RUNNING TESTS

To run tests, simply run `pytest`. If you want to test against the demo env, add `--functional`
