from django.contrib import admin
from .models import Studio,StudioSlot,StudioPhoto,Booking

@admin.register(Studio,StudioSlot,StudioPhoto,Booking)
class StudioReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self,request): return False
    def has_change_permission(self,request,obj=None): return False
    def has_delete_permission(self,request,obj=None): return False
