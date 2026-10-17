from datetime import datetime


_subtitle_state = {
    "input": "",
    "output": "",
    "updated_at": datetime.now().isoformat(timespec="seconds"),
}


def get_subtitles() -> dict:
    return dict(_subtitle_state)


def update_subtitles(input_text: str | None = None, output_text: str | None = None) -> dict:
    if input_text is not None:
        _subtitle_state["input"] = input_text.strip()
    if output_text is not None:
        _subtitle_state["output"] = output_text.strip()

    _subtitle_state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    return get_subtitles()
