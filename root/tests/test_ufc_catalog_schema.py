import sqlite3

import pytest

from src.app.db import connect, initialize_database


def test_ufc_catalog_schema_and_constraints(tmp_path):
    database_path = tmp_path / "tracker.db"
    initialize_database(database_path)

    with connect(database_path) as connection:
        event_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(events)")
        }
        assert {"location", "source_url"}.issubset(event_columns)

        fight_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(fights)")
        }
        assert {
            "fighter_a_id",
            "fighter_b_id",
            "winner_id",
            "result_method",
            "result_round",
            "result_time",
            "result_time_format",
            "referee",
            "result_details",
        }.issubset(fight_columns)

        fighter_id = connection.execute(
            """
            INSERT INTO fighters(canonical_name, first_name, last_name)
            VALUES ('Alpha Fighter', 'Alpha', 'Fighter')
            RETURNING id
            """
        ).fetchone()["id"]
        connection.execute(
            """
            INSERT INTO fighter_external_identities(
                fighter_id, provider, external_id, source_url
            ) VALUES (?, 'ufcstats', 'fighter-alpha', 'https://ufcstats.com/fighter-details/fighter-alpha')
            """,
            (fighter_id,),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO fighter_external_identities(
                    fighter_id, provider, external_id
                ) VALUES (?, 'ufcstats', 'fighter-alpha')
                """,
                (fighter_id,),
            )

        event_id = connection.execute(
            """
            INSERT INTO events(
                promotion, name, event_date, external_provider, external_id,
                location, source_url, status
            ) VALUES (
                'UFC', 'Catalog Card', '2026-01-01', 'ufcstats', 'event-alpha',
                'Las Vegas', 'https://ufcstats.com/event-details/event-alpha', 'completed'
            )
            RETURNING id
            """
        ).fetchone()["id"]
        fight_id = connection.execute(
            """
            INSERT INTO fights(
                event_id, fighter_a, fighter_b, fighter_a_id, fighter_b_id,
                bout_order, status, winner_id, result_method
            ) VALUES (?, 'Alpha Fighter', 'Beta Fighter', ?, ?, 1, 'completed', ?, 'Decision')
            RETURNING id
            """,
            (event_id, fighter_id, fighter_id, fighter_id),
        ).fetchone()["id"]
        connection.execute(
            """
            INSERT INTO fight_round_stats(
                fight_id, fighter_id, round_number, sig_strikes_landed,
                sig_strikes_attempted, control_seconds
            ) VALUES (?, ?, 1, 3, 10, 122)
            """,
            (fight_id, fighter_id),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO fight_round_stats(fight_id, fighter_id, round_number)
                VALUES (?, ?, 1)
                """,
                (fight_id, fighter_id),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO fight_round_stats(fight_id, fighter_id, round_number)
                VALUES (?, ?, 0)
                """,
                (fight_id, fighter_id),
            )
