# Rust AutoConnect — серверный A2S-прober

Постоянно работающий наблюдатель: спрашивает игровые серверы напрямую по
A2S и кладёт настоящий статус в общий кэш, который читают все копии
приложения.

## Зачем

Общий кэш серверов наполнялся данными стороннего агрегатора
(`gamemonitoring.net`): задержка в минуты, «средняя» точность времени вайпа
и полное отсутствие серверов, которых нет в его каталоге. Прober отвечает на
вопрос «сервер живой прямо сейчас?» настоящим UDP-запросом за секунды.

Побочный, но важный эффект: постоянные обращения не дают бесплатному
Supabase-проекту уснуть — а именно из-за засыпания периодически отваливались
Swarm, Telegram, лидерборд и общий кэш.

## Границы (важно)

- Прober **только читает** публичные A2S-ответы игровых серверов — ровно то
  же самое, что делает сам десктопный клиент. Никакого RCON, никакого
  вмешательства в игру, никаких игровых аккаунтов.
- **Ничего не хранит на диске.** Очередь приходит с бэкенда, результаты
  уходят обратно. Состояния нет.
- Сервер, на котором он живёт, общий — там работают другие проекты. Юнит
  ограничен по памяти/процессору (`MemoryMax`, `CPUQuota`, `Nice`,
  `IOSchedulingClass=idle`) специально, чтобы прober физически не мог
  ухудшить их работу.

## Установка (Debian 13, systemd)

```bash
sudo mkdir -p /opt/rust-autoconnect-prober/state
sudo chown -R "$USER":"$USER" /opt/rust-autoconnect-prober
git clone <repo> /opt/rust-autoconnect-prober/app
python3 -m venv /opt/rust-autoconnect-prober/venv
/opt/rust-autoconnect-prober/venv/bin/pip install -r /opt/rust-autoconnect-prober/app/tools/server_prober/requirements.txt
```

Секреты — в отдельный файл, не в юнит и не в git:

```bash
sudo tee /opt/rust-autoconnect-prober/prober.env >/dev/null <<'EOF'
PROBER_API_URL=https://<project>.supabase.co/functions/v1
PROBER_SECRET=<секрет прober'а>
PROBER_CYCLE_SECONDS=60
PROBER_CONCURRENCY=10
PROBER_BATCH_LIMIT=200
EOF
sudo chmod 600 /opt/rust-autoconnect-prober/prober.env
```

Сначала запустить **вручную**, посмотреть вывод и потребление памяти, и
только потом включать автозапуск:

```bash
set -a; . /opt/rust-autoconnect-prober/prober.env; set +a
cd /opt/rust-autoconnect-prober/app && /opt/rust-autoconnect-prober/venv/bin/python -u tools/server_prober/prober.py
```

Когда всё в порядке:

```bash
sudo cp /opt/rust-autoconnect-prober/app/tools/server_prober/rust-autoconnect-prober.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now rust-autoconnect-prober
journalctl -u rust-autoconnect-prober -f
```

## Настройки

| Переменная | По умолчанию | Смысл |
|---|---|---|
| `PROBER_API_URL` | — | Базовый URL Supabase Edge Functions |
| `PROBER_SECRET` | — | Секрет прober'а (только у него и у функции) |
| `PROBER_CYCLE_SECONDS` | `60` | Пауза между кругами опроса |
| `PROBER_CONCURRENCY` | `10` | Сколько серверов опрашивать одновременно |
| `PROBER_BATCH_LIMIT` | `200` | Максимум адресов за круг |

Опрос — это отправка UDP-пакета и ожидание ответа, поэтому процессор он
почти не тратит; потолок в 10 одновременных запросов выбран из уважения к
соседям по машине, а не из-за нагрузки на сеть.
