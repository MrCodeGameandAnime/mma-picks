def format_money(cents: int | None) -> str:
    return f"${(cents or 0) / 100:,.2f}"


def format_american_date(value: str | None) -> str:
    if not value:
        return ""
    try:
        year, month, day = value.split("-", 2)
        return f"{month}/{day}/{year}"
    except ValueError:
        return value



def format_height(value: int | None) -> str:
    if value is None:
        return ""
    feet, inches = divmod(int(value), 12)
    return f"{feet}'{inches}\""


def format_reach(value: int | float | None) -> str:
    if value is None:
        return ""
    inches = int(float(value) + 0.5)
    return f"{inches} in"


def format_weight_class(value: str | None) -> str:
    if not value:
        return ""
    return value.removesuffix(" Bout")


def format_tape_value(value: object, field: str) -> object:
    if field == "height_inches":
        return format_height(value)  # type: ignore[arg-type]
    if field == "reach_inches":
        return format_reach(value)  # type: ignore[arg-type]
    if field == "date_of_birth":
        return format_american_date(value)  # type: ignore[arg-type]
    return value
