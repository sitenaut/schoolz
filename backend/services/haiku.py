"""The Haiku model every scan, extraction and translation call uses, and the
request settings that go with it.

Haiku 5.5 is a tenth of Haiku 4.5's per-token price. In side-by-sides on real
newsletters, flyer images and calendar items it matched or beat 4.5. It
rejects any temperature but the default, so `temperature=0` is gone; thinking
is off at low effort, because these are transcription and extraction calls
and thinking tokens are billed as output.
"""

MODEL = "claude-haiku-5-5"

CALL_KWARGS = {
    "thinking": {"type": "disabled"},
    "extra_body": {"output_config": {"effort": "low"}},
}
