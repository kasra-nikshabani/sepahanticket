from django.contrib import admin
from .models import Course, Enrollment, Lesson, LessonProgress


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ['title', 'teacher_name', 'kind', 'status', 'enrollment_open']
    list_filter = ['kind', 'status']
    search_fields = ['title', 'teacher_name']

    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False


@admin.register(Enrollment, LessonProgress)
class EducationReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False


@admin.register(Lesson)
class LessonAdmin(EducationReadOnlyAdmin):
    exclude = ['source']
    list_display = ['title', 'course', 'state', 'is_preview']
