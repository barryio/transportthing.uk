from django.forms import ModelForm, Textarea, TextInput, CharField, IntegerField
from django import forms
from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction
from django.db.models import Exists, OuterRef, Q
from django.urls import reverse
from django.utils.html import format_html
from simple_history.admin import SimpleHistoryAdmin
from sql_util.utils import SubqueryCount


from . import models

UserModel = get_user_model()


class BulkVehicleCreationForm(ModelForm):
    """Form for bulk vehicle creation"""

    vehicle_codes = CharField(
        widget=Textarea(attrs={'rows': 10, 'cols': 50}),
        help_text="Enter vehicle codes, one per line (e.g., YY67_HBG, YJ18_DHC)",
        required=True
    )
    vehicle_regs = CharField(
        widget=Textarea(attrs={'rows': 10, 'cols': 50}),
        help_text="Optional: Enter vehicle registrations, one per line (must match number of vehicle codes). Leave blank if not available.",
        required=False
    )
    fleet_numbers = CharField(
        widget=Textarea(attrs={'rows': 10, 'cols': 50}),
        required=False,
        help_text="Optional: Enter fleet numbers, one per line (must match number of vehicle codes). Leave blank to use sequential numbering."
    )

    fleet_number_start = IntegerField(
        required=False,
        help_text="Optional: Starting fleet number (will auto-increment for each vehicle). Ignored if fleet numbers are specified above."
    )

    class Meta:
        model = models.Vehicle
        fields = ['operator', 'source', 'vehicle_type', 'livery']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Make vehicle_type and livery optional
        self.fields['vehicle_type'].required = False
        self.fields['livery'].required = False

    def clean(self):
        cleaned_data = super().clean()
        vehicle_codes_text = cleaned_data.get('vehicle_codes', '').strip()
        fleet_numbers_text = cleaned_data.get('fleet_numbers', '').strip()
        vehicle_regs_text = cleaned_data.get('vehicle_regs', '').strip()

        vehicle_codes = []
        if vehicle_codes_text:
            vehicle_codes = [code.strip() for code in vehicle_codes_text.split('\n') if code.strip()]

        vehicle_regs = []
        if vehicle_regs_text:
            vehicle_regs = [reg.strip() for reg in vehicle_regs_text.split('\n') if reg.strip()]

        fleet_numbers = []
        if fleet_numbers_text:
            fleet_numbers = [num.strip() for num in fleet_numbers_text.split('\n') if num.strip()]

        # Validate counts match if provided
        if vehicle_codes:
            if fleet_numbers and len(vehicle_codes) != len(fleet_numbers):
                raise forms.ValidationError(
                    f"Number of vehicle codes ({len(vehicle_codes)}) must match number of fleet numbers ({len(fleet_numbers)})"
                )
            if vehicle_regs and len(vehicle_codes) != len(vehicle_regs):
                raise forms.ValidationError(
                    f"Number of vehicle codes ({len(vehicle_codes)}) must match number of vehicle registrations ({len(vehicle_regs)})"
                )

        return cleaned_data


class BulkVehicleCreation(models.Vehicle):
    """Proxy model for bulk vehicle creation"""
    class Meta:
        proxy = True
        verbose_name = "Bulk Vehicle Creation"
        verbose_name_plural = "Bulk Vehicle Creation"
        permissions = [
            ("bulk_add_vehicle", "Can bulk add vehicles"),
        ]


@admin.register(models.VehicleType)
class VehicleTypeAdmin(admin.ModelAdmin):
    search_fields = ("name",)
    list_filter = ("style", "fuel")
    list_display = ("id", "name", "vehicles", "style", "fuel")
    list_editable = ("name", "style", "fuel")
    actions = ["merge"]

    @admin.display(ordering="vehicles")
    def vehicles(self, obj):
        return obj.vehicles

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if "changelist" in request.resolver_match.view_name:
            return queryset.annotate(vehicles=SubqueryCount("vehicle"))
        return queryset

    def merge(self, request, queryset):
        first = queryset[0]
        models.Vehicle.objects.filter(vehicle_type__in=queryset).update(
            vehicle_type=first
        )
        models.VehicleRevision.objects.filter(from_type__in=queryset).update(
            from_type=first
        )
        models.VehicleRevision.objects.filter(to_type__in=queryset).update(
            to_type=first
        )


class VehicleAdminForm(ModelForm):
    class Meta:
        widgets = {
            "fleet_number": TextInput(attrs={"style": "width: 4em"}),
            "fleet_code": TextInput(attrs={"style": "width: 4em"}),
            "reg": TextInput(attrs={"style": "width: 8em"}),
            "operator": TextInput(attrs={"style": "width: 4em"}),
            "branding": TextInput(attrs={"style": "width: 8em"}),
            "name": TextInput(attrs={"style": "width: 8em"}),
        }


def user(obj):
    return format_html(
        '<a href="{}">{}</a>',
        reverse("admin:accounts_user_change", args=(obj.user_id,)),
        obj.user,
    )


class VehicleCodeInline(admin.TabularInline):
    model = models.VehicleCode


class DuplicateVehicleFilter(admin.SimpleListFilter):
    title = "duplicate"
    parameter_name = "duplicate"

    def lookups(self, request, model_admin):
        return (
            ("reg", "same reg"),
            ("operator", "same reg and operator"),
            ("fleet_code", "same fleet code"),
            ("code", "same code"),
        )

    def queryset(self, request, queryset):
        if value := self.value():
            duplicates = models.Vehicle.objects.filter(~Q(id=OuterRef("id")))
            if value == "code":
                duplicates = duplicates.filter(code__iexact=OuterRef("code"))
            elif value == "fleet_code":
                duplicates = duplicates.filter(code__iexact=OuterRef("fleet_code"))
            else:
                # reg
                duplicates = duplicates.filter(reg__iexact=OuterRef("reg"))
                # reg and operator
                if value == "operator":
                    duplicates = duplicates.filter(operator=OuterRef("operator"))

            queryset = queryset.filter(~Q(reg__iexact=""), Exists(duplicates))

        return queryset


@admin.register(models.Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "fleet_number",
        "fleet_code",
        "reg",
        "operator",
        "vehicle_type",
        "get_flickr_link",
        "withdrawn",
        "last_seen",
        "livery",
        "colours",
        "branding",
        "name",
        "notes",
        "data",
    )
    list_filter = (
        DuplicateVehicleFilter,
        "withdrawn",
        "features",
        "vehicle_type",
        ("source", admin.RelatedOnlyFieldListFilter),
        ("operator", admin.RelatedOnlyFieldListFilter),
    )
    list_select_related = ["operator", "livery", "vehicle_type", "latest_journey"]
    list_editable = (
        "fleet_number",
        "fleet_code",
        "reg",
        "operator",
        "branding",
        "name",
        "notes",
    )
    autocomplete_fields = ("vehicle_type", "livery")
    raw_id_fields = ("operator", "source", "latest_journey")
    search_fields = ("code", "fleet_code", "reg")
    ordering = ("-id",)
    actions = (
        "copy_livery",
        "copy_type",
        "make_livery",
        "deduplicate",
        "spare_ticket_machine",
        "lock",
        "unlock",
    )
    inlines = [VehicleCodeInline]
    readonly_fields = ["latest_journey_data"]

    def copy_livery(self, request, queryset):
        livery = models.Livery.objects.filter(vehicle__in=queryset).first()
        count = queryset.update(livery=livery)
        self.message_user(request, f"Copied {livery} to {count} vehicles.")

    def copy_type(self, request, queryset):
        vehicle_type = models.VehicleType.objects.filter(vehicle__in=queryset).first()
        count = queryset.update(vehicle_type=vehicle_type)
        self.message_user(request, f"Copied {vehicle_type} to {count} vehicles.")

    def make_livery(self, request, queryset):
        vehicle = queryset.first()
        if vehicle.colours and vehicle.branding:
            livery = models.Livery.objects.create(
                name=vehicle.branding, colours=vehicle.colours, published=True
            )
            vehicles = models.Vehicle.objects.filter(
                colours=vehicle.colours, branding=vehicle.branding
            )
            count = vehicles.update(colours="", branding="", livery=livery)
            self.message_user(request, f"Updated {count} vehicles.")
        else:
            self.message_user(request, "Select a vehicle with colours and branding.")

    def deduplicate(self, request, queryset):
        for vehicle in queryset.order_by("id"):
            if not vehicle.reg and not vehicle.fleet_code:
                self.message_user(request, f"{vehicle} has no reg")
                continue
            try:
                if vehicle.reg:
                    duplicate = models.Vehicle.objects.get(
                        id__lt=vehicle.id,
                        operator=vehicle.operator_id,
                        reg__iexact=vehicle.reg,
                    )  # vehicle with lower id number we will keep
                else:
                    duplicate = models.Vehicle.objects.get(
                        id__lt=vehicle.id,
                        operator=vehicle.operator_id,
                        fleet_code__iexact=vehicle.fleet_code,
                    )  # vehicle with lower id number we will keep
            except (
                models.Vehicle.DoesNotExist,
                models.Vehicle.MultipleObjectsReturned,
            ) as e:
                self.message_user(request, f"{vehicle} {e}")
                continue
            try:
                vehicle.vehiclejourney_set.update(vehicle=duplicate)
            except IntegrityError:
                pass
            vehicle.vehiclecode_set.update(vehicle=duplicate)
            vehicle.vehiclerevision_set.update(vehicle=duplicate)
            if (
                not duplicate.latest_journey_id
                or vehicle.latest_journey_id
                and vehicle.latest_journey_id > duplicate.latest_journey_id
            ):
                duplicate.code = vehicle.code
                duplicate.latest_journey = vehicle.latest_journey
            vehicle.latest_journey = None
            vehicle.save(update_fields=["latest_journey"])
            duplicate.save(update_fields=["latest_journey"])
            duplicate.fleet_code = vehicle.fleet_code
            duplicate.fleet_number = vehicle.fleet_number
            if duplicate.withdrawn and not vehicle.withdrawn:
                duplicate.withdrawn = False
            vehicle.delete()
            duplicate.save(
                update_fields=["code", "fleet_code", "fleet_number", "reg", "withdrawn"]
            )
            self.message_user(
                request,
                format_html(
                    "{} deleted, merged with <a href='{}'>{}</a>",
                    vehicle,
                    duplicate.get_absolute_url(),
                    duplicate,
                ),
            )

    def spare_ticket_machine(self, request, queryset):
        queryset.update(
            reg="",
            fleet_code="",
            fleet_number=None,
            name="",
            colours="",
            livery=None,
            branding="",
            vehicle_type=None,
            notes="Spare ticket machine",
        )

    def lock(self, request, queryset):
        queryset.update(locked=True)

    def unlock(self, request, queryset):
        queryset.update(locked=False)





    @admin.display(ordering="latest_journey__datetime")
    def last_seen(self, obj):
        if obj.latest_journey:
            return obj.latest_journey.datetime

    def get_changelist_form(self, request, **kwargs):
        kwargs.setdefault("form", VehicleAdminForm)
        return super().get_changelist_form(request, **kwargs)

    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path('bulk-add/', self.admin_site.admin_view(self.bulk_add_view), name='vehicles_vehicle_bulk_add'),
        ]
        return custom_urls + urls

    def bulk_add_view(self, request):
        """Custom view for bulk vehicle creation"""
        # Create a temporary admin instance for the bulk creation form
        bulk_admin = BulkVehicleCreationAdmin(BulkVehicleCreation, self.admin_site)
        return bulk_admin.add_view(request)


class BulkVehicleCreationAdmin(admin.ModelAdmin):
    """Admin for bulk vehicle creation"""
    form = BulkVehicleCreationForm
    autocomplete_fields = ("vehicle_type", "livery")
    raw_id_fields = ("operator", "source")

    def has_module_permission(self, request):
        return request.user.has_perm('vehicles.bulk_add_vehicle')

    def has_view_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        # Handle the bulk creation logic here
        try:
            # Call the bulk creation method directly
            result = self._perform_bulk_creation(form.cleaned_data)
            messages.success(
                request,
                f"Successfully processed {result['attempted']} vehicles. "
                f"Created {result['created']} new vehicles, "
                f"skipped {result['skipped']} existing ones."
            )
        except Exception as e:
            messages.error(request, f"Error creating vehicles: {e}")

        # Don't actually save the proxy object
        pass

    def _perform_bulk_creation(self, cleaned_data):
        """Perform the actual bulk vehicle creation"""
        operator = cleaned_data['operator']
        source = cleaned_data['source']
        vehicle_codes_text = cleaned_data['vehicle_codes']
        fleet_numbers_text = cleaned_data.get('fleet_numbers', '').strip()
        vehicle_regs_text = cleaned_data.get('vehicle_regs', '').strip()
        fleet_number_start = cleaned_data.get('fleet_number_start')
        vehicle_type = cleaned_data.get('vehicle_type')
        livery = cleaned_data.get('livery')

        vehicle_codes = [code.strip() for code in vehicle_codes_text.strip().split('\n') if code.strip()]
    

        # Parse fleet numbers if provided
        fleet_numbers = []
        if fleet_numbers_text:
            fleet_numbers = [num.strip() for num in fleet_numbers_text.split('\n') if num.strip()]
            # Convert to integers, skip invalid entries
            fleet_numbers = [int(num) for num in fleet_numbers if num.isdigit()]

        vehicle_regs = []
        if vehicle_regs_text:
            vehicle_regs = [reg.strip() for reg in vehicle_regs_text.strip().split('\n') if reg.strip()]

        created_count = 0
        skipped_count = 0
        current_fleet_number = fleet_number_start

        with transaction.atomic():
            for i, vehicle_code in enumerate(vehicle_codes):
                # Check if vehicle already exists for this operator
                if models.Vehicle.objects.filter(code=vehicle_code, operator=operator).exists():
                    skipped_count += 1
                    continue
                
                # Create the vehicle
                vehicle_data = {
                    'code': vehicle_code,
                    'operator': operator,
                    'source': source,
                }

                if vehicle_type:
                    vehicle_data['vehicle_type'] = vehicle_type
                if livery:
                    vehicle_data['livery'] = livery

                # Handle fleet number assignment
                if fleet_numbers and i < len(fleet_numbers):
                    # Use individual fleet number
                    vehicle_data['fleet_number'] = fleet_numbers[i]
                elif current_fleet_number is not None:
                    # Use sequential numbering
                    vehicle_data['fleet_number'] = current_fleet_number
                    current_fleet_number += 1

                # Handle vehicle registration assignment
                if vehicle_regs and i < len(vehicle_regs):
                    vehicle_data['reg'] = vehicle_regs[i]

                models.Vehicle.objects.create(**vehicle_data)
                created_count += 1

        return {
            'attempted': len(vehicle_codes),
            'created': created_count,
            'skipped': skipped_count,
        }

    def response_add(self, request, obj, post_url_continue=None):
        # Redirect to the vehicle changelist after bulk creation
        from django.http import HttpResponseRedirect
        from django.urls import reverse
        return HttpResponseRedirect(reverse('admin:vehicles_vehicle_changelist'))








class UserFilter(admin.SimpleListFilter):
    title = "user"
    parameter_name = "user"

    def lookups(self, request, model_admin):
        lookups = {
            "Trusted": "Trusted",
            "Banned": "Banned",
            "None": "None",
        }
        if self.value() and self.value() not in lookups:
            lookups[self.value()] = self.value()
        return lookups.items()

    def queryset(self, request, queryset):
        match self.value():
            case "Trusted":
                return queryset.filter(user__trusted=True)
            case "Banned":
                return queryset.filter(user__trusted=False)
            case "None":
                return queryset.filter(user=None)
            case None:
                return queryset
        return queryset.filter(user=self.value())


@admin.register(models.VehicleJourney)
class VehicleJourneyAdmin(admin.ModelAdmin):
    list_display = (
        "datetime",
        "code",
        "vehicle",
        "route_name",
        "service",
        "destination",
    )
    list_select_related = ("vehicle", "service")
    raw_id_fields = ("vehicle", "service", "source", "trip")
    list_filter = (
        "datetime",
        ("service", admin.EmptyFieldListFilter),
        ("trip", admin.EmptyFieldListFilter),
        "source",
        "vehicle__operator",
    )
    show_full_result_count = False
    ordering = ("-id",)

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if "changelist" in request.resolver_match.view_name and not request.GET:
            # no filter yet - return empty queryset rather than trying to load ALL journeys
            return queryset.none()
        return queryset


class LiveryAdminForm(ModelForm):
    class Meta:
        widgets = {
            "colours": Textarea,
            "css": Textarea,
            "left_css": Textarea,
            "right_css": Textarea,
        }


def preview(obj, css):
    if obj.text_colour:
        text_colour = obj.text_colour
    elif obj.white_text:
        text_colour = "#fff"
    else:
        text_colour = "#222"
    if obj.stroke_colour:
        stroke = f"stroke:{obj.stroke_colour};stroke-width:3px;paint-order:stroke"
    else:
        stroke = ""

    return format_html(
        """<svg height="24" width="36" style="line-height:24px;font-size:24px;background:{}">
                <text x="50%" y="80%" fill="{}" text-anchor="middle" style="{}">42</text>
            </svg>""",
        css,
        text_colour,
        stroke,
    )


@admin.register(models.Livery)
class LiveryAdmin(SimpleHistoryAdmin):
    form = LiveryAdminForm
    search_fields = ["name"]
    actions = ["merge"]
    save_as = True
    list_display = [
        "id",
        "name",
        "vehicles",
        "left",
        "right",
        "blob",
        "published",
        "updated_at",
    ]
    list_filter = [
        "published",
        "updated_at",
        ("vehicle__operator", admin.RelatedOnlyFieldListFilter),
    ]
    ordering = ["-id"]

    readonly_fields = ["left", "right", "blob", "updated_at"]
    # specify order:
    fields = [
        "name",
        "colour",
        "blob",
        "colours",
        "angle",
        "horizontal",
        "text_colour",
        "white_text",
        "stroke_colour",
        "left_css",
        "right_css",
        "left",
        "right",
        "published",
        "updated_at",
    ]

    class Media:
        js = ["js/livery-admin.js"]

    def merge(self, request, queryset):
        queryset = queryset.order_by("id")
        if not all(
            queryset[0].colours == livery.colours
            and queryset[0].left_css == livery.left_css
            and queryset[0].right_css == livery.right_css
            for livery in queryset
        ):
            self.message_user(
                request, "You can only merge liveries that are the same", messages.ERROR
            )
        else:
            for livery in queryset[1:]:
                livery.vehicle_set.update(livery=queryset[0])
                livery.revision_from.update(from_livery=queryset[0])
                livery.revision_to.update(to_livery=queryset[0])
            self.message_user(request, "Merged")

    @admin.display(ordering="right_css")
    def right(self, obj):
        return preview(obj, obj.right_css)

    @admin.display(ordering="left_css")
    def left(self, obj):
        return preview(obj, obj.left_css)

    @admin.display(ordering="colour")
    def blob(self, obj):
        if obj.colour:
            return format_html(
                """<svg width="20" height="20">
                    <circle fill="{}" r="10" cx="10" cy="10"></circle>
                </svg>""",
                obj.colour,
            )

    vehicles = VehicleTypeAdmin.vehicles

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if "changelist" in request.resolver_match.view_name:
            return queryset.annotate(vehicles=SubqueryCount("vehicle"))
        return queryset


class RevisionChangeFilter(admin.SimpleListFilter):
    title = "changed field"
    parameter_name = "change"

    def lookups(self, request, model_admin):
        return (
            ("changes__reg", "reg"),
            ("changes__name", "name"),
            ("changes__branding", "branding"),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value and value.startswith("changes__"):
            return queryset.filter(**{f"{value}__isnull": False})
        return queryset


@admin.register(models.VehicleRevision)
class VehicleRevisionAdmin(admin.ModelAdmin):
    raw_id_fields = [
        "from_operator",
        "to_operator",
        "from_livery",
        "to_livery",
        "from_type",
        "to_type",
        "vehicle",
        "user",
        "approved_by",
    ]

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    list_display = ["created_at", "vehicle", "__str__", user, "message"]
    actions = ["revert"]
    list_filter = [
        RevisionChangeFilter,
        UserFilter,
        ("vehicle__operator", admin.RelatedOnlyFieldListFilter),
    ]
    list_select_related = ["from_operator", "to_operator", "vehicle", "user"]

    def revert(self, request, queryset):
        for revision in queryset.prefetch_related("vehicle"):
            for message in revision.revert():
                self.message_user(request, message)


@admin.register(models.VehicleCode)
class VehicleCodeAdmin(admin.ModelAdmin):
    raw_id_fields = ["vehicle"]
    list_display = ["id", "scheme", "code", "vehicle"]
    list_filter = ["scheme"]

@admin.register(models.SiriSubscription)
class SiriSubscriptionAdmin(admin.ModelAdmin):
    readonly_fields = ["uuid", "sample"]

admin.site.register(models.VehicleFeature)

