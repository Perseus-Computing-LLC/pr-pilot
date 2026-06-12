
def get_user_bad(user_id):
    """Deliberately insecure — should be caught."""
    query = "SELECT * FROM users WHERE id = " + user_id
    return db.execute(query)

def get_user_good(user_id):
    """Parameterized — correct."""
    query = "SELECT * FROM users WHERE id = ?"
    return db.execute(query, (user_id,))
