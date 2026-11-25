from django.db import models


class Learner(models.Model):
    phone = models.CharField(max_length=15, unique=True, help_text="E.164 format, e.g. +2547XXXXXXXX")
    name = models.CharField(max_length=100)
    level = models.CharField(max_length=50, help_text="e.g. 'Grade 6', 'Form 2'")
    parent_phone = models.CharField(max_length=15, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.phone})"


class Subject(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Lesson(models.Model):
    subject = models.ForeignKey(Subject, related_name="lessons", on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    manual_content = models.TextField(
        blank=True,
        help_text="Pre-written fallback lesson text, used if no generated content exists.",
    )
    generated_content = models.TextField(
        blank=True,
        help_text="LLM-generated lesson summary (filled in later by the document upload feature).",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} ({self.subject.name})"

    def get_content(self):
        """Prefer generated content; fall back to manually written content."""
        return self.generated_content.strip() or self.manual_content.strip()


class Question(models.Model):
    CHOICE_NUMBERS = [(1, "1"), (2, "2"), (3, "3"), (4, "4")]

    lesson = models.ForeignKey(Lesson, related_name="questions", on_delete=models.CASCADE)
    text = models.CharField(max_length=300)
    choice_1 = models.CharField(max_length=200)
    choice_2 = models.CharField(max_length=200)
    choice_3 = models.CharField(max_length=200)
    choice_4 = models.CharField(max_length=200)
    correct_choice = models.PositiveSmallIntegerField(choices=CHOICE_NUMBERS)
    is_generated = models.BooleanField(default=False)

    def __str__(self):
        return self.text

    def choices(self):
        return [self.choice_1, self.choice_2, self.choice_3, self.choice_4]


class QuizAttempt(models.Model):
    FEEDBACK_CHOICES = [
        ("easy", "Easy"),
        ("ok", "OK"),
        ("hard", "Hard"),
    ]

    learner = models.ForeignKey(Learner, related_name="quiz_attempts", on_delete=models.CASCADE)
    lesson = models.ForeignKey(Lesson, related_name="quiz_attempts", on_delete=models.CASCADE)
    score = models.PositiveSmallIntegerField(default=0)
    total_questions = models.PositiveSmallIntegerField(default=3)
    reward_paid = models.BooleanField(default=False)
    feedback = models.CharField(max_length=10, choices=FEEDBACK_CHOICES, blank=True, null=True)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"{self.learner.name} - {self.lesson.title} ({self.score}/{self.total_questions})"


class Announcement(models.Model):
    subject = models.ForeignKey(
        Subject, related_name="announcements", on_delete=models.SET_NULL, null=True, blank=True
    )
    level = models.CharField(
        max_length=50, blank=True, help_text="Target level, e.g. 'Form 2'. Leave blank to target everyone."
    )
    message = models.CharField(max_length=320)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.message[:50]
