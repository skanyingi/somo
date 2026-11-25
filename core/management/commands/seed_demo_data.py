from django.core.management.base import BaseCommand

from core.models import Learner, Lesson, Question, Subject


class Command(BaseCommand):
    help = "Create sample subjects, lessons, questions and a learner for local testing."

    def handle(self, *args, **options):
        maths, _ = Subject.objects.get_or_create(name="Mathematics")
        english, _ = Subject.objects.get_or_create(name="English")

        lesson, created = Lesson.objects.get_or_create(
            subject=maths,
            title="Fractions Basics",
            defaults={
                "manual_content": (
                    "A fraction shows part of a whole. The top number (numerator) tells you how many "
                    "parts you have. The bottom number (denominator) tells you how many equal parts "
                    "make up the whole. Example: 3/4 means 3 out of 4 equal parts."
                )
            },
        )

        if created:
            Question.objects.bulk_create([
                Question(
                    lesson=lesson,
                    text="In 3/4, what is the number 4 called?",
                    choice_1="Numerator",
                    choice_2="Denominator",
                    choice_3="Whole number",
                    choice_4="Decimal",
                    correct_choice=2,
                ),
                Question(
                    lesson=lesson,
                    text="What does a fraction represent?",
                    choice_1="A whole number",
                    choice_2="Part of a whole",
                    choice_3="A percentage only",
                    choice_4="None of these",
                    correct_choice=2,
                ),
                Question(
                    lesson=lesson,
                    text="Which fraction is equal to one half?",
                    choice_1="1/4",
                    choice_2="2/3",
                    choice_3="2/4",
                    choice_4="3/4",
                    correct_choice=3,
                ),
            ])

        Lesson.objects.get_or_create(
            subject=english,
            title="Nouns and Verbs",
            defaults={
                "manual_content": (
                    "A noun names a person, place or thing (e.g. teacher, Nairobi, book). A verb shows "
                    "an action or state (e.g. run, is, think). Every complete sentence needs at least "
                    "one noun and one verb."
                )
            },
        )

        Learner.objects.get_or_create(
            phone="+254700000001",
            defaults={
                "name": "Demo Learner",
                "level": "Grade 6",
                "parent_phone": "+254700000002",
            },
        )

        self.stdout.write(self.style.SUCCESS("Sample data ready."))
