This library provides an interface with the Kalshi exchange. You can find the Kalshi API
documentation here: https://trading-api.readme.io/reference/getting-started/.
Kalshi has a demo env (https://demo.kalshi.co) where we can test our code.
We also currently have a local "fake" instance of the Kalshi exchange that mocks the Kalshi
endpoints. Please do not use production credentials unless we are legally cleared for trading.
We do not intend to trade real money for the forseeable future; therefore, this repository
is currently only for educational and research purposes unless there is a change in the
direction of the project.

### SETUP

- Make sure you have python `3.11.2`
- Install the virtual env library with `pip3.11 install virtualenv`. This is where we will host all your dependencies for this project.
- Create a directory for your venv `mkdir venv`
- Create a venv `cd venv && python3.11 -m venv . && cd ..`
- Activate the venv with `source venv/bin/activate`. From now on, you will need to activate the venv before development. You can add this command to your zsh/bash profile so you don't have to do it everytime you log in
- Install poetry with pipx. For mac: to install pipx do, `brew install pipx`, then do `pipx install poetry`. Run `pipx ensurepath` to add it to your path. Run `poetry install` to install the dependencies to your venv. If you're on a different OS: the purpose of pipx is to intall poetry, so just find a way to install poetry. Here are the docs: https://python-poetry.org/docs/
- Set up some default formatters in vs code. This will help keep your code clean. I'd recommend black and isort. Also set up autoformat on save (https://stackoverflow.com/questions/59433286/vs-code-prettier-format-on-save-doesnt-work). This is an example of what my user settings.json looks like in vs code:

```
{
    "python.formatting.provider": "black",
    "python.formatting.blackArgs": ["--line-length=88"],
    "editor.formatOnSave": true,
    "python.analysis.autoImportCompletions": true,
    "python.autoComplete.extraPaths": [
        "${workspaceFolder}/"
    ],
    "python.analysis.extraPaths": [
        "${workspaceFolder}/"
    ],
    "python.analysis.indexing": true,
    "python.analysis.packageIndexDepths": [
        {
            "name": "",
            "depth": 20,
            "includeAllSymbols": true
        }
    ],
    "workbench.editor.enablePreview": false,
    "window.zoomLevel": 2,
    "security.workspace.trust.untrustedFiles": "open",
    "[python]": {
        "editor.defaultFormatter": "ms-python.black-formatter",
        "editor.formatOnType": true
    },
}
```

### CREDENTIALS

Credentials will be necessary for running tests and connecting to the Kalshi demo exchange.
Do not put production credentials in unless you know what you're doing.
To setup your demo credentials, first create an account on Kalshi's demo exchange here:
https://demo.kalshi.co.

Next, you will need to export these three variables in your local environment (explained later):

- API_URL (example: https://demo-api.kalshi.co/trade-api)
- API_VERSION (example: v2)
- API_USERNAME
- API_PASSWORD

In order for tests to pass, you need these env vars. These vars are used for functional
tests and some regular testing. You can automatically add these env vars
by creating a bash script like so:

```
#!/bin/sh

export API_URL='https://demo-api.kalshi.co/trade-api'
export API_VERSION='v2'
export API_USERNAME='your-email@email.com'
export API_PASSWORD='some-password'
```

And then adding the following to your bash / zsh profile: `source path/to/your/script.sh`.
In order for functional tests to pass, your username and passowrd should coorespond to
an actual username and password on Kalshi's demo website.

### RUNNING TESTS

To run tests, simply run `pytest -n auto`. There are three layers of testing: unit testing, integration testing,
and functional testing. Unit testing is for testing very small units of the code. Integration testing tests
connections between different parts of the code. Functional testing will be reserved for communication with
the Kalshi exchange. Functional testing basically runs unit and integration tests, but instead of hitting
the local "fake" Kalshi exchange that we wrote, it hits the demo Kalshi exchange. Please use functional tests
sparingly, since we don't want to hit the Kalshi exchange a lot. This is why we set up a local fake instance
of Kalshi for most of our testing. If you want to run funtional tests against the demo env in Kalshi,
run `pytest -n auto --functional`. You can also get a coverage report with missed lines by running:

```
coverage erase &&
pytest -n auto --cov=src/ tests/ --cov-append &&
coverage report --show-missing --skip-covered
```

Code coverage let's you know how much of your code you've tested. It also let's you know which lines are not tested.

### CREATING A PULL REQUEST

- Create a new branch called something like `feature/rate_limit` or `bug_fix/README` etc.
- Write all your code there, and make sure you add type hints where appropriate
- Write unit and integration tests for your code
- Add documentation in the README.md or anywhere appropriat
- Run the tests with the command `pytest -n auto`
- After tests are passing, check your code coverage report and make sure it's as close to 100% as possible (see `RUNNING TESTS` section above)
- Use the following structure for your commits: first, run `git add .`. Then, run `git commit`. Note: we have pre-commits enabled. Pre-commits
  will essentially re-format your code, type check, remove unnecessary code, and spot other errors. It will auto-fix some of the errors, but you
  will need to manually fix some of the other errors. After you fix your pre-commit issues, run the following again: `git add .` and `git commit`
  (or `git commit --amend`, explained later). In the commit message, the top line will be the title of your pull request. The next few lines
  are a description for the pull request. Then do `git push` -- you might have to copy and paste the command that it says. For subsequent
  pushes to teh branch branch, please use `git commit --amend` and `git push --force-with-lease`. This will push it to the same commit to the same branch.
  The purpose of doing `git commit --amend` instead of a new commit is so that we don't have a large number of commits per PR.
- Once your PR is ready for review, open a pull request, and everything should be automatically filled. Wait for the PR to be reviewed, fix the issues, then merge.

### DEPENDENCIES

If you need to add a new third party library, please use `poetry add <library_name>`. To remove it, use `poetry remove <library_name>`.
