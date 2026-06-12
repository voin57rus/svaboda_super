#!/bin/bash
# ===============================
# Svaboda Admin Installer FIXED v3
# С поддержкой WireGuard/AmneziaWG
# ===============================

set -e

cd /root || exit 1

INSTALL_DIR="/root/svaboda_admin"
REPO_URL="git@github.com:voin57rus/svaboda_admin.git"
VENV_DIR="$INSTALL_DIR/venv"
SERVICE_NAME="svaboda_admin"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

print_header() {
    echo -e "\n${CYAN}========================================${NC}"
    echo -e "${CYAN}  $1${NC}"
    echo -e "${CYAN}========================================${NC}\n"
}

print_ok()    { echo -e "${GREEN}[✓]${NC} $1"; }
print_warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
print_err()   { echo -e "${RED}[✗]${NC} $1"; }
print_info()  { echo -e "${CYAN}[i]${NC} $1"; }

# ========================================

escape_sed() {
    echo "$1" | sed -e 's/[\/&|]/\\&/g'
}

# ========================================
# Проверка WireGuard/AmneziaWG
# ========================================
check_wireguard() {
    print_header "Проверка WireGuard/AmneziaWG"

    # Docker
    if ! command -v docker &>/dev/null; then
        print_err "Docker не найден!"
        return 1
    fi
    print_ok "Docker: $(docker --version)"

    # WG контейнер
    WG_CONTAINER=$(docker ps --format '{{.Names}}' | grep -i "amnezia\|wireguard\|wg" || true)
    if [ -n "$WG_CONTAINER" ]; then
        print_ok "WG контейнер запущен: $WG_CONTAINER"
    else
        print_warn "WG контейнер не найден в running!"
        WG_STOPPED=$(docker ps -a --format '{{.Names}}' | grep -i "amnezia\|wireguard\|wg" || true)
        if [ -n "$WG_STOPPED" ]; then
            print_warn "Найден остановленный: $WG_STOPPED"
            docker start "$WG_STOPPED" 2>/dev/null && print_ok "Запущен!" || print_err "Не удалось запустить"
        else
            print_warn "WG контейнер не найден — создай его для работы WireGuard"
        fi
    fi

    # Порт WG
    if ss -ulnp 2>/dev/null | grep -qE "39623|51820"; then
        print_ok "WG порт слушается"
    else
        print_warn "WG порт не слушается (39623/UDP)"
    fi
    echo ""
}

# ========================================
# Проверка SSH ключа GitHub
# ========================================
check_github_ssh() {
    print_header "Проверка GitHub SSH"

    SSH_KEY=""
    for KEY_FILE in "$HOME/.ssh/id_ed25519" "$HOME/.ssh/id_rsa" "$HOME/.ssh/id_ecdsa"; do
        if [ -f "$KEY_FILE" ]; then
            SSH_KEY="$KEY_FILE"
            break
        fi
    done

    if [ -z "$SSH_KEY" ]; then
        print_warn "SSH ключ не найден!"
        print_info "Генерирую новый ключ..."
        ssh-keygen -t ed25519 -C "svaboda-server" -f "$HOME/.ssh/id_ed25519" -N ""
        SSH_KEY="$HOME/.ssh/id_ed25519"
        print_ok "Ключ создан: $SSH_KEY"
        print_warn "⚠️ ДОБАВЬ ПУБЛИЧНЫЙ КЛЮЧ В GITHUB!"
        echo ""
        cat "${SSH_KEY}.pub"
        echo ""
        read -p "Нажми Enter после добавления ключа в GitHub..."
    else
        print_ok "SSH ключ найден: $SSH_KEY"
    fi

    if ssh -T -o StrictHostKeyChecking=no -o ConnectTimeout=5 git@github.com 2>&1 | grep -q "successfully\|You've successfully"; then
        print_ok "GitHub SSH работает"
    else
        print_warn "GitHub SSH не подтверждён"
    fi
    echo ""
}

# ========================================
# Настройка конфигурации
# ========================================
ask_config() {
    print_header "Настройка конфигурации"

    if [ "$AUTO_MODE" = "1" ]; then
        NEED_WRITE_CONFIG=1
        return
    fi

    if [ -f "$INSTALL_DIR/config.py" ]; then
        read -p "Использовать существующий config.py? (Y/n): " ans
        ans=${ans:-Y}
        if [[ "$ans" =~ ^[YyДд]$ ]]; then
            NEED_WRITE_CONFIG=0
            return
        fi
    fi

    echo -e "${CYAN}Введи данные для config.py:${NC}"
    read -p "BOT_TOKEN: " BOT_TOKEN
    read -p "ADMIN_ID (твой Telegram ID): " ADMIN_ID
    NEED_WRITE_CONFIG=1
}

write_config() {
    if [ "$NEED_WRITE_CONFIG" != "1" ]; then return; fi

    if [ ! -f "$INSTALL_DIR/config.py.example" ]; then
        print_warn "config.py.example не найден, пропускаю"
        return
    fi

    cp "$INSTALL_DIR/config.py.example" "$INSTALL_DIR/config.py"

    BOT_TOKEN_ESC=$(escape_sed "$BOT_TOKEN")
    ADMIN_ID_ESC=$(escape_sed "$ADMIN_ID")

    sed -i "s|ВАШ_ТОКЕН_БОТА|$BOT_TOKEN_ESC|g" "$INSTALL_DIR/config.py"
    sed -i "s|123456789|$ADMIN_ID_ESC|g" "$INSTALL_DIR/config.py"

    print_ok "config.py настроен"
}

# ========================================
# Установка зависимостей
# ========================================
install_deps() {
    print_header "Установка зависимостей"

    apt-get update -qq
    apt-get install -y python3-venv python3-pip git curl jq

    # Docker если нет
    if ! command -v docker &>/dev/null; then
        print_info "Установка Docker..."
        curl -fsSL https://get.docker.com | sh
        systemctl enable docker
        systemctl start docker
        print_ok "Docker установлен"
    fi

    print_ok "Зависимости установлены"
    echo ""
}

# ========================================
# Virtual environment
# ========================================
setup_venv() {
    print_header "Virtual environment"

    python3 -m venv "$VENV_DIR"
    source "$VENV_DIR/bin/activate"

    pip install --upgrade pip 2>&1 | tail -1
    pip install -r "$INSTALL_DIR/requirements.txt" 2>&1 | tail -3

    # Проверка модулей
    print_info "Проверка модулей..."
    ERRORS=0
    for MODULE in aiogram aiohttp qrcode pillow asyncssh paramiko; do
        if python3 -c "import $MODULE" 2>/dev/null; then
            print_ok "$MODULE"
        else
            print_err "$MODULE — НЕ УСТАНОВЛЕН!"
            ERRORS=$((ERRORS + 1))
        fi
    done

    [ $ERRORS -gt 0 ] && print_err "Есть недостающие модули!" || true
    echo ""
}

# ========================================
# Проверка WireGuard файлов
# ========================================
check_wg_files() {
    print_header "Проверка WireGuard файлов"

    WG_FILES=(
        "bot/handlers/user/protocol_select.py"
        "bot/handlers/user/payments/wireguard_pay.py"
        "bot/handlers/user/help_wireguard.py"
        "bot/services/panels/wireguard_ssh.py"
        "bot/services/panels/wireguard_service.py"
        "bot/services/vpn_api.py"
        "bot/services/billing.py"
        "bot/handlers/user/keys.py"
        "bot/keyboards/user.py"
        "bot/utils/key_generator.py"
        "bot/utils/key_sender.py"
        "database/db_keys.py"
        "database/db_payments.py"
        "database/migrations.py"
    )

    WG_OK=0
    for FILE in "${WG_FILES[@]}"; do
        if [ -f "$INSTALL_DIR/$FILE" ]; then
            echo -e "  ${GREEN}✓${NC} $FILE"
            WG_OK=$((WG_OK + 1))
        else
            echo -e "  ${RED}✗${NC} $FILE — НЕ НАЙДЕН!"
        fi
    done

    echo ""
    print_info "WireGuard файлов: $WG_OK / ${#WG_FILES[@]}"

    if [ $WG_OK -lt ${#WG_FILES[@]} ]; then
        print_warn "Не все WG файлы на месте! Обнови репозиторий."
    fi
    echo ""
}

# ========================================
# systemd сервис
# ========================================
setup_systemd() {
    print_header "systemd"

    cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Svaboda Admin Bot
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
ExecStart=$VENV_DIR/bin/python3 main.py
Restart=always
RestartSec=10
StandardOutput=append:$INSTALL_DIR/bot.log
StandardError=append:$INSTALL_DIR/bot.log

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable "$SERVICE_NAME"
    print_ok "Сервис $SERVICE_NAME создан и включён"
    echo ""
}

# ========================================
# Запуск бота
# ========================================
start_bot() {
    print_header "Запуск бота"

    systemctl stop "$SERVICE_NAME" 2>/dev/null || true
    pkill -f "python3 main.py" 2>/dev/null || true
    sleep 2

    systemctl start "$SERVICE_NAME"
    sleep 3

    if systemctl is-active --quiet "$SERVICE_NAME"; then
        print_ok "Бот успешно запущен!"
        echo ""
        print_info "Последние строки лога:"
        tail -15 "$INSTALL_DIR/bot.log" 2>/dev/null || echo "  (лог ещё пуст)"
    else
        print_err "Ошибка запуска бота!"
        echo ""
        print_info "Лог:"
        cat "$INSTALL_DIR/bot.log" 2>/dev/null || echo "  (лог пуст)"
        echo ""
        systemctl status "$SERVICE_NAME" --no-pager 2>/dev/null || true
    fi
    echo ""
}

# ========================================
# Полная установка
# ========================================
do_install() {
    print_header "🚀 УСТАНОВКА"

    # 1. GitHub SSH
    check_github_ssh

    # 2. WireGuard
    check_wireguard

    # 3. Клонирование
    print_header "Клонирование репозитория"

    systemctl stop "$SERVICE_NAME" 2>/dev/null || true

    if [ -d "$INSTALL_DIR/.git" ]; then
        print_info "Репозиторий существует, обновляю..."
        cd "$INSTALL_DIR"
        git pull origin main 2>&1 || git pull origin master 2>&1
        print_ok "Обновлено"
    else
        print_info "Клонирую..."
        rm -rf "$INSTALL_DIR"
        git clone "$REPO_URL" "$INSTALL_DIR" 2>&1
        print_ok "Клонировано в $INSTALL_DIR"
    fi
    echo ""

    # 4. Проверка WG файлов
    check_wg_files

    # 5. Конфигурация
    ask_config

    # 6. Зависимости
    install_deps

    # 7. Config
    write_config

    # 8. Venv
    setup_venv

    # 9. systemd
    setup_systemd

    # 10. Запуск
    start_bot

    # Итог
    print_header "✅ ГОТОВО"

    echo -e "  ${GREEN}Бот:${NC}     $INSTALL_DIR"
    echo -e "  ${GREEN}Venv:${NC}     $VENV_DIR"
    echo -e "  ${GREEN}Сервис:${NC}   $SERVICE_NAME"
    echo -e "  ${GREEN}Лог:${NC}      $INSTALL_DIR/bot.log"
    echo ""
    echo -e "  ${CYAN}Команды:${NC}"
    echo "    systemctl status $SERVICE_NAME"
    echo "    systemctl restart $SERVICE_NAME"
    echo "    systemctl stop $SERVICE_NAME"
    echo "    tail -f $INSTALL_DIR/bot.log"
    echo "    cd $INSTALL_DIR && git pull && systemctl restart $SERVICE_NAME"
    echo ""
}

# ========================================
# Меню
# ========================================
show_menu() {
    clear
    echo -e "${CYAN}"
    echo "  ╔══════════════════════════════════════╗"
    echo "  ║   SVABODA ADMIN INSTALLER v3         ║"
    echo "  ║   WireGuard + AmneziaWG              ║"
    echo "  ╚══════════════════════════════════════╝"
    echo -e "${NC}"
    echo "  1) 🚀 Установка / Переустановка"
    echo "  2) 🔄 Обновить (git pull + restart)"
    echo "  3) 📋 Статус бота"
    echo "  4) 📜 Логи"
    echo "  5) 🔍 Проверить WireGuard"
    echo "  6) 🔑 Показать SSH ключ (для GitHub)"
    echo "  0) Выход"
    echo ""
    read -p "Выбор: " choice

    case $choice in
        1) do_install ;;
        2)
            cd "$INSTALL_DIR" && git pull && systemctl restart "$SERVICE_NAME"
            print_ok "Обновлено!"
            ;;
        3)
            systemctl status "$SERVICE_NAME" --no-pager
            ;;
        4)
            tail -30 "$INSTALL_DIR/bot.log" 2>/dev/null || echo "Лог пуст"
            ;;
        5) check_wireguard ;;
        6)
            echo ""
            for KEY in "$HOME/.ssh/id_ed25519.pub" "$HOME/.ssh/id_rsa.pub"; do
                if [ -f "$KEY" ]; then
                    echo "=== $KEY ==="
                    cat "$KEY"
                    echo ""
                fi
            done
            ;;
        0) exit 0 ;;
        *) echo "Неверно" ;;
    esac

    echo ""
    read -p "Нажми Enter для продолжения..."
    show_menu
}

# ========================================

if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Запуск только от root!${NC}"
    echo "sudo bash $0"
    exit 1
fi

if [ -n "$1" ]; then
    export AUTO_MODE=1
    do_install
    exit 0
fi

show_menu
