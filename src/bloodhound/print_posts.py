# print_posts.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import distinct
from src.bloodhound.models import Post  # adjust import if needed

DB_PATH = "sqlite:///bloodhound.db"  # change path if needed

def main():
    engine = create_engine(DB_PATH, echo=False)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # Print all posts
        print("=== All Posts ===")
        posts = session.query(Post).all()
        for post in posts:
            print({
                "channel_id": post.channel_id,
                "source_id": post.source_id,
                "type": post.type.value if post.type else None,
                "district": post.district,
                "metro": post.metro,
                "address": post.address,
                "rooms": post.rooms,
                "size_sqm": post.size_sqm,
                "floor": post.floor,
                "price": post.price,
                "pets": post.pets,
                "tenants": post.tenants,
                "created_at": post.created_at,
                "updated_at": post.updated_at,
                "deleted": post.deleted,
            })

        # Print distinct values
        print("\n=== Distinct Values ===")

        distinct_pets = [row[0] for row in session.query(distinct(Post.pets)).filter(Post.pets.isnot(None)).all()]
        distinct_districts = [row[0] for row in session.query(distinct(Post.district)).filter(Post.district.isnot(None)).all()]
        distinct_metros = [row[0] for row in session.query(distinct(Post.metro)).filter(Post.metro.isnot(None)).all()]

        print("Pets:", distinct_pets)
        print("Districts:", distinct_districts)
        print("Metros:", distinct_metros)

    finally:
        session.close()

if __name__ == "__main__":
    main()
