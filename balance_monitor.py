"""Детерминированный контроль небаланса. Python 3.10+, без зависимостей.

Вход: завершённые суточные записи daily_data, тоннажи, не накопительные счётчики.
Пропуски/нечисловые значения не заменяются нулём. Причины не диагностируются.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

VERSION = "2026.09.15-formulas-windows-v2"

DISPLAY_FIELDS = {
    1: (("kv4", "К4"), ("kv4d", "К4Д (дубль)"), ("kv14", "К14"),
        ("kv32", "К32"), ("kv34", "К34"), ("kv102", "К102"),
        ("kv24p", "К24ПП"), ("kv24hv", "К24ХВ"), ("kv28a1", "К28А.I"),
        ("kv34a", "К10/34А")),
    2: (("kv3", "К3"), ("kv3d", "К3Д (дубль)"), ("kv15", "К15"),
        ("kv31", "К31"), ("kv33", "К33"), ("kv101", "К101"),
        ("kv28a2", "К28А.II"), ("kv19", "К19")),
}
SYMBOLIC = {
    "Б1": "К102 + К34 + К24ПП + К24ХВ − К28А.I − К4",
    "БС1": "К102 + К24ХВ + К24ПП + К32 − К28А.I − К14",
    "Б2": "К101 + К33 − К28А.II − К3",
    "БС2": "К101 + К31 − К28А.II − К15",
}


def display_number(value, signed=False):
    value = Decimal(str(value))
    # До точности исходных показаний, без округления промежуточных расчётов.
    text = format(value, "+,f" if signed else ",f").replace(",", " ")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text.replace(".", ",")


def display_pct(value):
    if value is None:
        return "—"
    if abs(value) < Decimal("0.005"):
        return "0%"
    text = f"{value:+.2f}".rstrip("0").rstrip(".")
    return text.replace(".", ",") + "%"


def status_icon(item):
    return {"норма": "✅", "предупреждение": "⚠️", "критично": "🚨"}.get(item["status"], "⬜")


def render_daily_details(row, norms=None, warn=2, crit=5):
    """Показания, доли от входа и полная подстановка в четыре формулы."""
    norms = norms or {}
    day = record_date(row)
    parts = []
    for queue, base_key, names in ((1, "kv4", ("Б1", "БС1")), (2, "kv3", ("Б2", "БС2"))):
        base_label = "К4" if queue == 1 else "К3"
        lines = [f"🧮 Суточный расчёт · {day:%d.%m.%Y}", f"🏭 Очередь {queue}",
                 f"⚖️ Показания весов · тонны и доля от {base_label}"]
        try:
            base = number(row, base_key)
        except ValueError:
            base = None
        for key, label in DISPLAY_FIELDS[queue]:
            try:
                value = number(row, key)
                share = value / base * 100 if base else None
                share_label = "—" if share is None else display_pct(share).lstrip("+")
                line = f"{label}: {display_number(value)} т · {share_label}"
                if key in norms and share is not None:
                    lo, hi = norms[key][:2]
                    icon = "✅" if Decimal(str(lo)) <= share <= Decimal(str(hi)) else "⚠️"
                    line += f" {icon} ориентир {lo}–{hi}%"
                lines.append(line)
            except ValueError:
                lines.append(f"{label}: нет показания")
        lines.append("Дубли показаны для сравнения, к входу не прибавляются.")
        for name in names:
            result = calculate([row], name, warn, crit)
            lines.extend(["", f"{status_icon(result)} {name} · формула и подстановка",
                          f"Δ = {SYMBOLIC[name]}"])
            if result["error"]:
                lines.append(f"Нет расчёта: {result['error']}")
                continue
            _, positive, negative = SPECS[name]
            substitution = " + ".join(display_number(number(row, k)) for k in positive)
            substitution += " − " + " − ".join(display_number(number(row, k)) for k in negative)
            lines.append(f"Δ = {substitution} = {display_number(result['delta'], signed=True)} т")
            lines.append(f"{name} = Δ / {base_label} × 100%")
            if result["pct"] is None:
                lines.append(f"{base_label} = 0 т. Процент не рассчитан; разность в тоннах показана выше.")
            else:
                lines.append(f"{name} = {display_number(result['delta'], signed=True)} / "
                             f"{display_number(result['base'])} × 100% = {display_pct(result['pct'])}")
                lines.append(f"Итог: {display_pct(result['pct'])} · {result['status']}")
                if name in ("Б1", "Б2"):
                    accounted = result['base'] + result['delta']
                    lines.append(f"Учтённые выходы минус возврат: {display_number(accounted)} т; "
                                 f"{display_pct(accounted / result['base'] * 100).lstrip('+')} от входа.")
        lines.append("Доля потока — не выполнение плана. Небаланс — не доказанный объём потерь.")
        parts.append("\n".join(lines))
    return parts


def render_selected_window(rows, end, today, days, warn=2, crit=5):
    if days not in (1, 3, 5, 7):
        raise ValueError("Выберите 1, 3, 5 или 7 дней")
    by_date = prepare(rows, end, today)
    start = end - timedelta(days=days - 1)
    dates = [start + timedelta(days=i) for i in range(days)]
    lines = [f"📉 Скользящий баланс · {days} дн.", f"{start:%d.%m.%Y} — {end:%d.%m.%Y}",
             "Б — общий баланс; БС — баланс сепарации."]
    for queue, names in ((1, ("Б1", "БС1")), (2, ("Б2", "БС2"))):
        lines.extend(["", f"🏭 Очередь {queue}"])
        for day in dates:
            if day not in by_date:
                lines.append(f"{day:%d.%m} · нет завершённых данных")
                continue
            result = [calculate([by_date[day]], name, warn, crit) for name in names]
            b = display_pct(result[0].get("pct"))
            bs = display_pct(result[1].get("pct"))
            lines.append(f"{day:%d.%m} · Б {b}  |  БС {bs}")
    lines.extend(["", "📊 Итог за выбранный период"])
    w = window(by_date, end, days, warn, crit)
    if w["missing"]:
        lines.append("Не рассчитан: нет завершённых данных за " + ", ".join(f"{d:%d.%m}" for d in w["missing"]) + ".")
    else:
        for queue, names in ((1, ("Б1", "БС1")), (2, ("Б2", "БС2"))):
            lines.append(f"Очередь {queue}:")
            for name in names:
                item = w["balances"][name]
                if item["error"]:
                    lines.append(f"{name}: нет расчёта — {item['error']}")
                elif item["pct"] is None:
                    lines.append(f"{name}: —; Δ {display_number(item['delta'], True)} т; вход 0 т")
                else:
                    lines.append(f"{status_icon(item)} {name}: {display_pct(item['pct'])} · "
                                 f"Δ {display_number(item['delta'], True)} т / вход {display_number(item['base'])} т")
    lines.extend(["", "Итог = сумма разностей, т / сумма входа, т × 100%. Суточные проценты не усредняются.",
                  "«—» означает отсутствие расчёта, а не нулевой небаланс."])
    if (today - end).days > 1:
        lines.append("Показан исторический срез: отчёт заканчивается раньше последних завершённых суток.")
    return "\n".join(lines)
SPECS = {
    "Б1": ("kv4", ("kv102", "kv34", "kv24p", "kv24hv"), ("kv28a1", "kv4")),
    "БС1": ("kv4", ("kv102", "kv24hv", "kv24p", "kv32"), ("kv28a1", "kv14")),
    "Б2": ("kv3", ("kv101", "kv33"), ("kv28a2", "kv3")),
    "БС2": ("kv3", ("kv101", "kv31"), ("kv28a2", "kv15")),
}
ZERO = Decimal(0)


def record_date(row):
    explicit = row.get("report_date")
    parts = None
    if all(row.get(k) is not None for k in ("year", "month", "day_num")):
        parts = date(int(row["year"]), int(row["month"]), int(row["day_num"]))
    if explicit:
        parsed = date.fromisoformat(str(explicit))
        if parts is not None and parts != parsed:
            raise ValueError("Противоречивые даты записи")
        return parsed
    if parts is None:
        raise ValueError("Отсутствует дата записи")
    return parts


def number(row, key):
    if key not in row or row[key] is None or isinstance(row[key], bool):
        raise ValueError(f"нет показания {key}")
    try:
        value = Decimal(str(row[key]))
    except InvalidOperation as exc:
        raise ValueError(f"нечисловое показание {key}") from exc
    if not value.is_finite() or value < 0:
        raise ValueError(f"недопустимый тоннаж {key}")
    return value


def status(pct, warn=2, crit=5):
    warn, crit = Decimal(str(warn)), Decimal(str(crit))
    if not (ZERO <= warn < crit) or not warn.is_finite() or not crit.is_finite():
        raise ValueError("Некорректные пороги баланса")
    if pct is None:
        return "нет расчёта"
    return "критично" if abs(pct) > crit else "предупреждение" if abs(pct) > warn else "норма"


def calculate(rows, name, warn=2, crit=5):
    base_key, positive, negative = SPECS[name]
    try:
        daily = []
        for row in rows:
            base = number(row, base_key)
            delta = sum((number(row, k) for k in positive), ZERO) - sum(
                (number(row, k) for k in negative), ZERO)
            daily.append((base, delta))
        base = sum((b for b, _ in daily), ZERO)
        delta = sum((d for _, d in daily), ZERO)
        pct = delta / base * 100 if base else None
        return {"base": base, "delta": delta, "pct": pct, "status": status(pct, warn, crit),
                "active_days": sum(b > 0 for b, _ in daily),
                "negative_sum": sum((d for _, d in daily if d < 0), ZERO),
                "positive_sum": sum((d for _, d in daily if d > 0), ZERO), "error": None}
    except ValueError as exc:
        return {"error": str(exc), "status": "нет расчёта"}


def prepare(rows, end, today):
    if isinstance(today, datetime):
        today = today.date()
    if isinstance(end, datetime):
        end = end.date()
    if end >= today:
        raise ValueError("Конец завершённого периода должен быть раньше текущей даты")
    by_date = {}
    for raw in rows:
        row = dict(raw)
        day = record_date(row)
        if day > today:
            raise ValueError(f"В базе есть будущая дата {day:%d.%m.%Y}; сначала исправьте импорт")
        if day >= today or day > end:
            continue
        if row.get("is_complete") in (False, 0):
            continue
        if day in by_date:
            raise ValueError(f"Дублируется дата {day:%d.%m.%Y}; нужна одна итоговая запись")
        by_date[day] = row
    return by_date


def window(by_date, end, days, warn=2, crit=5):
    dates = [end - timedelta(days=i) for i in reversed(range(days))]
    missing = [d for d in dates if d not in by_date]
    result = {"start": dates[0], "end": end, "days": days, "missing": missing}
    result["balances"] = {} if missing else {
        name: calculate([by_date[d] for d in dates], name, warn, crit) for name in SPECS}
    return result


def episodes(by_date, end, warn=2, crit=5):
    """История от последнего возобновления входного учёта; не дата пуска агрегата.

    Предыдущий день с нулевым входом используется только как отметка наблюдения.
    Уровни бункеров из тоннажей не выводятся. Нулевые дни после пуска сохраняются.
    """
    contiguous = []
    cursor = end
    while cursor in by_date:
        contiguous.append(cursor)
        cursor -= timedelta(days=1)
    contiguous.reverse()
    result = []
    for queue, base, names in ((1, "kv4", ("Б1", "БС1")), (2, "kv3", ("Б2", "БС2"))):
        start = contiguous[0] if contiguous else None
        observed = False
        try:
            for prev, cur in zip(contiguous, contiguous[1:]):
                if number(by_date[prev], base) == 0 and number(by_date[cur], base) > 0:
                    start, observed = cur, True
            selected = [by_date[d] for d in contiguous if start is not None and d >= start]
            balances = {name: calculate(selected, name, warn, crit) for name in names} if selected else {}
            result.append({"queue": queue, "start": start, "end": end, "observed": observed,
                           "balances": balances, "error": None})
        except ValueError as exc:
            result.append({"queue": queue, "error": str(exc), "balances": {}})
    return result


def analyze(rows, end, today, warn=2, crit=5):
    by_date = prepare(rows, end, today)
    return {"end": end, "today": today,
            "windows": [window(by_date, end, n, warn, crit) for n in (1, 2, 3, 7)],
            "episodes": episodes(by_date, end, warn, crit)}


def metric(name, item):
    if item["error"]:
        return f"{name}: НЕТ РАСЧЁТА — {item['error']}"
    percent = "НЕТ РАСЧЁТА: вход 0 т" if item["pct"] is None else f"{item['pct']:+.2f}%"
    return (f"{name}: {item['delta']:+.2f} т / {item['base']:.2f} т; "
            f"{percent}; {item['status']}")


def stable_alerts(report):
    w = next(w for w in report["windows"] if w["days"] == 3)
    if w["missing"]:
        return [("warn", "Трёхсуточный сигнал недоступен: отсутствуют завершённые даты.")]
    alerts = []
    for name, item in w["balances"].items():
        prefix = f"[3 суток {w['start']:%d.%m}–{w['end']:%d.%m.%Y}] "
        if item["error"]:
            alerts.append(("warn", prefix + metric(name, item)))
        elif item["status"] in ("предупреждение", "критично"):
            qualifier = ("Небаланс за 3 календарных суток; вход был только в "
                         f"{item['active_days']} из 3 суток. " if item["active_days"] < 3 else
                         "Устойчивый сигнал по правилу окна 3 суток. ")
            alerts.append(("crit" if item["status"] == "критично" else "warn",
                           prefix + qualifier + metric(name, item)))
        elif item["pct"] is None and item["delta"] != 0:
            alerts.append(("warn", prefix + metric(name, item) + "; есть движение при нулевом входе"))
    return alerts


def render(report):
    lines = ["📉 Контроль небаланса и межсуточного перехода",
             f"Данные по {report['end']:%d.%m.%Y}. Текущая смена отдельно.",
             "Знак: выходы минус учтённые возвраты и вход. Проценты — от К4/К3."]
    if (report["today"] - report["end"]).days > 1:
        lines.append("Внимание: отчёт заканчивается раньше вчерашней даты; это исторический срез.")
    for w in report["windows"]:
        lines.append(f"\nОкно {w['days']} сут.: {w['start']:%d.%m}–{w['end']:%d.%m.%Y}")
        if w["missing"]:
            lines.append("НЕТ РАСЧЁТА — нет дат: " + ", ".join(f"{d:%d.%m}" for d in w["missing"]))
            continue
        for name, item in w["balances"].items():
            lines.append(metric(name, item))
    lines.append("\nТрёхсуточный сигнал:")
    alerts = stable_alerts(report)
    lines.extend(text for _, text in alerts)
    if not alerts:
        lines.append("Превышения порогов по доступным процентам нет. НЕТ РАСЧЁТА не означает норму.")
    lines.append("\nНакопленный небаланс:")
    for ep in report["episodes"]:
        if ep["error"]:
            lines.append(f"Очередь {ep['queue']}: {ep['error']}")
            continue
        if not ep["balances"]:
            lines.append(f"Очередь {ep['queue']}: нет завершённых данных на конец периода")
            continue
        label = "от возобновления входного учёта" if ep["observed"] else "от начала доступного непрерывного ряда"
        lines.append(f"Очередь {ep['queue']}, {label} {ep['start']:%d.%m.%Y}:")
        for name, item in ep["balances"].items():
            lines.append(metric(name, item))
            if not item["error"]:
                lines.append(f"Сумма суточных минусов {item['negative_sum']:.2f} т; "
                             f"плюсов {item['positive_sum']:+.2f} т. Это не объём потерь.")
    lines.extend(["\nОкна 1/2/7 суток — справочные. Сигнал баланса — окно 3 суток.",
                  "Накопленный итог не заменяет окна: взаимная компенсация может скрывать отклонения.",
                  "Возобновление входного учёта не доказывает дату запуска дробления.",
                  "Остатки в бункерах не учтены. Небаланс не доказывает потерю руды или проскальзывание датчика.",
                  "Для проверки причины нужны синхронные показания, изменение остатков, маршруты и контроль весов."])
    return "\n".join(lines)


AI_RULES = """\nПРАВИЛА КОНТРОЛЯ НЕБАЛАНСА (приоритет над прежними предположениями):
Ни межсуточный переход руды, ни механическое проскальзывание датчика скорости
не устанавливаются из суточного баланса. Используй готовые детерминированные
расчёты ниже; не пересчитывай и не меняй пороги. Не называй небаланс потерями.
Суммировать надо тоннажи, а не проценты. Проценты БС1 и БС2 тоже от К4 и К3.
При нулевой базе процент недоступен, разность в тоннах сохраняется.
Нормализация окна — только арифметическая компенсация; причина не доказана.
Накопленный итог от возобновления входного учёта не равен запасу в бункерах.
Пуск, остановка и изменение маршрутов требуют проверки по оперативному журналу.
Порог баланса — правило проекта, не паспортная погрешность весов.
Отделяй факт, гипотезу, проверку и управленческое действие: кому, что, к какому
сроку и по какому результату закрыть проверку. Не предлагай подгонять весы под
ноль баланса. Не предлагай ждать три дня с проверкой явного суточного сбоя:
трёхсуточное правило относится к устойчивому сигналу баланса, а не к запрету осмотра.
"""
