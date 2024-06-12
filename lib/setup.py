"""
Module encapsulates shared configs & dependencies
"""
from lib.gateway import telegram
from lib.internal import configurator

PROD_ENV = "production"
DEV_ENV = "development"

app_config = configurator.Configurator(config_dir="./config")
TG_GW = telegram.TelegramGateway(
    bot_secret=app_config.telegram.bot_secret,
    chat_id=app_config.telegram.chat_id,
    log_chat_id=app_config.telegram.log_chat_id,
    timeout=app_config.telegram.timeout,
    rps_config=app_config.telegram.rps_config,
    rps_config_parsing_mode=app_config.telegram.rps_config_parsing_mode
)

