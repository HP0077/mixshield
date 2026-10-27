"""The 10 attacker goals (see docs/injection_tasks.md) and the candidate user-task rule."""

# (goal number, suite, AgentDojo injection task)
GOALS = [
    (0, "banking", "injection_task_0"),
    (1, "banking", "injection_task_4"),
    (2, "banking", "injection_task_6"),
    (3, "banking", "injection_task_8"),
    (4, "workspace", "injection_task_0"),
    (5, "banking", "injection_task_7"),
    (6, "workspace", "injection_task_3"),
    (7, "workspace", "injection_task_4"),
    (8, "slack", "injection_task_1"),
    (9, "slack", "injection_task_2"),
]

# The first version of the goals. Goal 5 was workspace injection_task_1 (delete file 13).
# It was retired on Day 2: the model sends the file ID as a number, the tool rejects it,
# so the goal could never succeed. Kept only to read the old result files.
GOALS_V1 = [g if g[0] != 5 else (5, "workspace", "injection_task_1") for g in GOALS]


def candidate_user_tasks(eligible: list[str], goals_in_suite: list[int]) -> dict[int, list[str]]:
    """Pick 3 candidate user tasks per goal of one suite, without looking at any result.

    `eligible` = user tasks with an injection point. Sort by number, then deal them
    out with a fixed stride so goals get different tasks spread over the whole suite.
    `goals_in_suite` = the goal numbers of that suite, in order. The result depends on
    how many goals the suite has, so goals 0-3 and 8-9 keep their original lists only
    when called with the original goal lists (see GOALS_V1).
    """
    ordered = sorted(eligible, key=lambda t: int(t.rsplit("_", 1)[1]))
    stride = len(ordered) // (3 * len(goals_in_suite))
    return {
        goal: [ordered[(j + len(goals_in_suite) * m) * stride] for m in range(3)]
        for j, goal in enumerate(goals_in_suite)
    }


# The 10 fixed pairs (docs/task_pairs.md): goal -> fixed user task. Never change.
FIXED_USER_TASK_V1 = {
    0: "user_task_8", 1: "user_task_1", 2: "user_task_2", 3: "user_task_7", 4: "user_task_24",
    5: "user_task_3", 6: "user_task_6", 7: "user_task_9", 8: "user_task_0", 9: "user_task_3",
}
# Current pairs. Goal 5 (banking) was chosen after the swap, see docs/task_pairs.md.
FIXED_USER_TASK = {**FIXED_USER_TASK_V1, 5: "user_task_9"}
