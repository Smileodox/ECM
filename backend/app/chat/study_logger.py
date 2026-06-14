import logging
import sys

logger = logging.getLogger(__name__)

TABLE_NAME = "userstudylogs"


async def log_turn(
    *,
    subject_id: str,
    study_session_id: str,
    turn_index: int,
    question: str,
    answer: str,
    program_name: str | None,
    route: str | None,
    query_type: str | None,
    answerability_score: float,
    num_citations: int,
    total_ms: float,
    language: str | None,
    connection_string: str,
) -> None:
    try:
        from azure.data.tables.aio import TableServiceClient

        entity = {
            "PartitionKey": subject_id,
            "RowKey": f"{study_session_id}_{turn_index:04d}",
            "StudySessionId": study_session_id,
            "TurnIndex": turn_index,
            "Question": question[:32768],
            "Answer": answer[:32768],
            "ProgramName": program_name or "",
            "Route": route or "",
            "QueryType": query_type or "",
            "AnswerabilityScore": answerability_score,
            "NumCitations": num_citations,
            "TotalMs": total_ms,
            "Language": language or "",
        }

        async with TableServiceClient.from_connection_string(connection_string) as svc:
            await svc.create_table_if_not_exists(TABLE_NAME)
            table = svc.get_table_client(TABLE_NAME)
            await table.upsert_entity(entity)

    except Exception:
        logger.exception("study_logger: failed to write turn", exc_info=True)
