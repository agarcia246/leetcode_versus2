from app.models import Problem, ProblemTopic, Topic


def add_problem(db, slug="two-sum", title="Two Sum", difficulty="Easy", topic="Array"):
    problem = Problem(
        title=title,
        lc_id=slug,
        lc_url=f"https://leetcode.com/problems/{slug}/",
        difficulty=difficulty,
    )
    db.add(problem)
    db.flush()

    topic_row = db.query(Topic).filter(Topic.topic_name == topic).first()
    if topic_row is None:
        topic_row = Topic(topic_name=topic)
        db.add(topic_row)
        db.flush()

    db.add(ProblemTopic(problem_id=problem.id, topic_id=topic_row.id))
    db.flush()
    return problem
