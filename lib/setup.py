"""
Module encapsulates shared configs & dependencies
"""
from lib.gateway import telegram
from lib.internal import configurator

app_config = configurator.Configurator(config_dir="./config")
TG_GW = telegram.TelegramGateway(
    bot_secret=app_config.telegram.bot_secret,
    chat_id=app_config.telegram.chat_id,
    log_chat_id=app_config.telegram.log_chat_id,
    timeout=app_config.telegram.timeout
)

