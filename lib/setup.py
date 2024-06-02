"""
Module encapsulates shared configs & dependencies
"""
from lib.internal import configurator

# TODO tg gateway

app_config = configurator.Configurator(config_dir="./config")

