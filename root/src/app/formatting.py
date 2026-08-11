def format_money(cents: int | None) -> str:
    return f"${(cents or 0) / 100:,.2f}"
