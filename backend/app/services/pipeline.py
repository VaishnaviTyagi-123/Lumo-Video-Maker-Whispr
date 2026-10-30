
"""End-to-end LangGraph video generation pipeline."""

from typing import Any, TypedDict

from langgraph.graph import StateGraph, START, END

from app.services.creative import (
    CreativePlan,
    run_creative_pipeline,
)
from app.services.voice import synthesize_voice
from app.services.render import render_product_video


MAX_AUDIO_ATTEMPTS = 3


class PipelineState(TypedDict, total=False):
    product: dict[str, Any]
    language: str
    voice: str

    plan: dict[str, Any]
    voice_result: dict[str, Any]
    video_result: dict[str, Any]

    attempts: int
    status: str
    error: str | None
    trace: list[dict[str, Any]]


def generate_creative(state: PipelineState) -> dict:
    """Generate a brand-compliant creative plan."""

    attempt = state.get("attempts", 0) + 1

    result = run_creative_pipeline(
        product=state["product"],
        language=state["language"],
    )

    trace = state.get("trace", []) + [
        {
            "node": "creative_generation",
            "attempt": attempt,
            "approved": result["approved"],
            "violations": result["violations"],
        }
    ]

    if not result["approved"]:
        return {
            "attempts": attempt,
            "status": "failed",
            "error": "Creative plan rejected by brand validator",
            "trace": trace,
        }

    return {
        "plan": result["plan"],
        "attempts": attempt,
        "status": "creative_approved",
        "error": None,
        "trace": trace,
    }


def route_after_creative(state: PipelineState) -> str:
    if state["status"] == "failed":
        return "failed"
    return "continue"


def generate_voice(state: PipelineState) -> dict:
    """Generate voice and measure whether it fits 15 seconds."""

    plan = CreativePlan.model_validate(state["plan"])

    try:
        result = synthesize_voice(
            plan=plan,
            language=state["language"],
            voice=state["voice"],
            product_id=state["product"]["id"],
        )

        return {
            "voice_result": result,
            "status": "voice_approved",
            "error": None,
            "trace": state.get("trace", []) + [
                {
                    "node": "voice_generation",
                    "attempt": state["attempts"],
                    "engine": result["engine_used"],
                    "original_duration": result["original_duration"],
                    "final_duration": result["final_duration"],
                    "alignment_status": result.get("alignment", {}).get("status"),
                    "aligned_word_count": result.get("alignment", {}).get("word_count", 0),
                    "caption_count": result.get("alignment", {}).get("caption_count", len(result.get("captions", []))),
                    "stages": [
                        "tts_generation",
                        "audio_normalization",
                        "whisperx_alignment",
                        "caption_grouping",
                    ],
                }
            ],
        }

    except RuntimeError as exc:
        return {
            "status": "voice_rejected",
            "error": str(exc),
            "trace": state.get("trace", []) + [
                {
                    "node": "voice_generation",
                    "attempt": state["attempts"],
                    "error": str(exc),
                }
            ],
        }


def route_after_voice(state: PipelineState) -> str:
    if state["status"] == "voice_approved":
        return "render"

    if (
        state["status"] == "voice_rejected"
        and state["attempts"] < MAX_AUDIO_ATTEMPTS
    ):
        return "retry"

    return "failed"


def render_video(state: PipelineState) -> dict:
    """Render the final MP4."""

    plan = CreativePlan.model_validate(state["plan"])

    result = render_product_video(
        product=state["product"],
        plan=plan,
        language=state["language"],
        voice_job_id=state["voice_result"]["job_id"],
    )

    return {
        "video_result": result,
        "status": "completed",
        "error": None,
        "trace": state.get("trace", []) + [
            {
                "node": "video_rendering",
                "render_id": result["render_id"],
                "duration": result["duration"],
            }
        ],
    }


def finish(state: PipelineState) -> dict:
    return {
        "trace": state.get("trace", []) + [
            {
                "node": "pipeline_complete",
                "status": state["status"],
            }
        ]
    }


builder = StateGraph(PipelineState)

builder.add_node("creative", generate_creative)
builder.add_node("voice", generate_voice)
builder.add_node("render", render_video)
builder.add_node("complete", finish)

builder.add_edge(START, "creative")

builder.add_conditional_edges(
    "creative",
    route_after_creative,
    {
        "continue": "voice",
        "failed": "complete",
    },
)

builder.add_conditional_edges(
    "voice",
    route_after_voice,
    {
        "retry": "creative",
        "render": "render",
        "failed": "complete",
    },
)

builder.add_edge("render", "complete")
builder.add_edge("complete", END)

pipeline_graph = builder.compile()


def run_video_pipeline(
    product: dict,
    language: str,
    voice: str,
) -> dict:
    """Execute the complete video generation workflow."""

    result = pipeline_graph.invoke(
        {
            "product": product,
            "language": language,
            "voice": voice,
            "attempts": 0,
            "status": "queued",
            "error": None,
            "trace": [],
        }
    )

    return {
        "status": result["status"],
        "error": result.get("error"),
        "attempts": result["attempts"],
        "plan": result.get("plan"),
        "voice": result.get("voice_result"),
        "video": result.get("video_result"),
        "trace": result["trace"],
    }
