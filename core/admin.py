from django.contrib import admin

from .models import Announcement, Learner, Lesson, Question, QuizAttempt, Subject


@admin.register(Learner)
class LearnerAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "level", "parent_phone", "created_at")
    search_fields = ("name", "phone", "parent_phone")
    list_filter = ("level",)


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


class QuestionInline(admin.TabularInline):
    model = Question
    extra = 1


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ("title", "subject", "created_at")
    list_filter = ("subject",)
    search_fields = ("title",)
    inlines = [QuestionInline]


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("text", "lesson", "correct_choice", "is_generated")
    list_filter = ("lesson__subject", "is_generated")
    search_fields = ("text",)


@admin.register(QuizAttempt)
class QuizAttemptAdmin(admin.ModelAdmin):
    list_display = ("learner", "lesson", "score", "total_questions", "reward_paid", "feedback", "started_at")
    list_filter = ("reward_paid", "feedback", "lesson__subject")
    search_fields = ("learner__name", "learner__phone")


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ("message", "subject", "level", "created_at", "sent_at")
    list_filter = ("subject", "level")
