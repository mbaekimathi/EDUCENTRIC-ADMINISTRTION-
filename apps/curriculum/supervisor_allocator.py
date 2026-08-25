import random


def shuffle_level_supervisors(subjects, subject_teacher_ids, supervisors, rng=None):
    """Assign one supervisor per subject for a merged academic level.

    Class teachers of a subject are skipped when another teacher is available.
    Supervisors are shuffled so duties rotate across the level rather than per class.
    """
    rng = rng or random.Random()
    pool = list(supervisors)
    assigned = {}
    if not subjects:
        return assigned
    if not pool:
        return {subject.id: None for subject in subjects}

    remaining = pool[:]
    rng.shuffle(remaining)

    for subject in subjects:
        excluded = set(subject_teacher_ids.get(subject.id) or ())
        candidates = [person for person in remaining if person.id not in excluded]
        if not candidates:
            candidates = [person for person in pool if person.id not in excluded]
        if not candidates:
            candidates = remaining or pool
        chosen = candidates[0]
        assigned[subject.id] = chosen
        remaining = [person for person in remaining if person.id != chosen.id]
        if not remaining:
            remaining = pool[:]
            rng.shuffle(remaining)
    return assigned
