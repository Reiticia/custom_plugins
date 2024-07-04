# Custom Plugins

## Pre action

1. install pipx

    ```shell
    python -m pip install --user pipx
    python -m pipx ensurepath
    ```

2. install pdm `pipx install pdm`
3. install nb-cli `pipx install nb-cli`

## How to start

1. install dependencies `pdm install`.
2. start project `nb run` .

## How to create a new plugin

1. create a new plugin `nb plugin create your_plugin_name`
2. Use nested plugin? No
3. Where to store the plugin? Other
4. Output Dir: plugin

## Documentation

See [Docs](https://nonebot.dev/)
