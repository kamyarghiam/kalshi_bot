This library provides an interface with the Kalshi exchange. There are strategies under the src/strategies folder

### SETUP ###
* Make sure you have python `3.11.2`
* Insteall virtual env with `pip3.11 install virtualenv`
* Create a directory for your venv `mkdir venv`
* `cd venv`
* Create a venv `python3.11 -m venv .`
* `cd ..`
* Activate the venv with `source venv/bin/activate`. From now on, you will need to activate the venv before development
* Install poetry with pipx. To install pipx do, `brew install pipx`, then do `pipx install poetry`
* Run `pipx ensurepath` to add it to your path
* Run `poetry install` to install the dependencies to your venv


### DESIGN ###

All the soure code is under the `/src` folder. Under the `/exchange` repository,
we have our interface with the exchange. This helps us keep track of information
locally vs on the exchange. We put all of our strategies under the strategies folder.

### RUNNING TESTS ###

To run tests, simply run `pytest`
