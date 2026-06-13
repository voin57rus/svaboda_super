# svaboda_super
установка .env:

cd /root/svaboda_super
ls -la
nano /root/svaboda_super/.env


BOT_TOKEN=НОВЫЙ_ТОКЕН_ОТ_BOTFATHER
ADMIN_IDS=1234567890
DATABASE_PATH=названия вашей базы данных
LOG_LEVEL=INFO


установка бота на сервер если в привате

создать ключ ssh
cd /root
rm -rf svaboda_super
git clone https://github.com/voin57rus/svaboda_super.git
cd svaboda_super
bash install_bot.sh

