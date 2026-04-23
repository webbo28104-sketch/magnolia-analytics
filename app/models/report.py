from app import db
from datetime import datetime


class Report(db.Model):
    __tablename__ = 'reports'

    id = db.Column(db.Integer, primary_key=True)
    round_id = db.Column(db.Integer, db.ForeignKey('rounds.id'), nullable=False, unique=True)

    # The generated HTML email content (legacy — kept for email delivery)
    html_content = db.Column(db.Text, nullable=True)

    # Plain text summary for SMS/push notifications (future)
    summary_text = db.Column(db.Text, nullable=True)

    # Claude-generated coaching narrative (plain text, ~3 paragraphs) — legacy
    # Superseded by insights_json; kept for backward compatibility.
    narrative_text = db.Column(db.Text, nullable=True)

    # Claude-generated insights JSON — single API call returning all interpretive
    # text for the report page. Populated on first view; cached thereafter.
    # Schema: see claude_service._empty_insights()
    insights_json = db.Column(db.Text, nullable=True)

    # Cached Open-Meteo weather snapshot for the round date/course
    # Stored as JSON string: {"temp_c": float, "wind_kph": float,
    #                         "precip_mm": float, "condition": str}
    weather_json = db.Column(db.Text, nullable=True)

    # Narrative version — bumped whenever prompt logic changes significantly.
    # On first view, if the stored version is lower than NARRATIVE_VERSION the
    # cached narrative is discarded and regenerated, then stamped with the new
    # version so it is only regenerated once per prompt generation change.
    narrative_version = db.Column(db.Integer, nullable=True)

    # Claude metadata
    prompt_tokens = db.Column(db.Integer, nullable=True)
    completion_tokens = db.Column(db.Integer, nullable=True)
    model_used = db.Column(db.String(100), nullable=True)

    # Status
    generated_at = db.Column(db.DateTime, nullable=True)
    emailed_at = db.Column(db.DateTime, nullable=True)
    email_status = db.Column(db.String(50), nullable=True)  # 'sent', 'failed', 'pending'

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Report round_id={self.round_id} status={self.email_status}>'
