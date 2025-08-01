import re
from typing import cast

from crispy_forms.helper import FormHelper
from crispy_forms.layout import HTML, Div, Field, Layout
from dal import autocomplete
from django import forms
from django.forms.models import inlineformset_factory  # ,BaseInlineFormSet
from django.utils.safestring import mark_safe
from django.utils.text import slugify

from proteins.models import (
    ProteinTF,
    ProteinCollection,
)
from proteins.validators import protein_sequence_validator, validate_doi
from references.models import Reference  # breaks application modularity


def popover_html(label, content, side="right"):
    return (
        '<label data-toggle="tooltip" style="padding-'
        + side
        + ': 1rem;" data-placement="'
        + side
        + '" title="'
        + content
        + '">'
        + label
        + "</label>"
    )


def check_existence(form, fieldname, value):
    # check whether another Protein already has this
    # value for this fieldname
    # return value if not
    if not value:
        return None

    # on update form allow for the same sequence (case insensitive)
    if hasattr(form, "instance"):
        instanceVal = getattr(form.instance, fieldname)
        if isinstance(instanceVal, str) and instanceVal.upper() == value.upper():
            return value

    if fieldname == "name":
        slug = slugify(value)
        query = Protein.objects.filter(slug=slug)
        query = query | Protein.objects.filter(name__iexact=value)
        query = query | Protein.objects.filter(name__iexact=value.replace(" ", ""))
        query = query | Protein.objects.filter(name__iexact=value.replace(" ", "").replace("monomeric", "m"))
    else:
        query = Protein.objects.filter(**{fieldname: value}).exclude(id=form.instance.id)

    if query.exists():
        prot = query.first()
        raise forms.ValidationError(
            mark_safe(
                f'<a href="{prot.get_absolute_url()}" style="text-decoration: underline;">'
                f"{prot.name}</a> already has this {Protein._meta.get_field(fieldname).verbose_name.lower()}"
            )
        )
    return value


class DOIField(forms.CharField):
    max_length = 100
    required = True
    default_validators = [validate_doi]

    def to_python(self, value):
        if value and isinstance(value, str):
            value = re.sub(r"^https?://(dx\.)?doi.org/", "", value)
        return super().to_python(value)


class SequenceField(forms.CharField):
    widget = forms.Textarea(attrs={"class": "vLargeTextField", "rows": 3})
    max_length = 1024
    label = "AA Sequence"
    default_validators = [protein_sequence_validator]
    strip = True

    def to_python(self, value):
        if value and isinstance(value, str):
            value = value.replace(" ", "").upper()
        return super().to_python(value)

class SelectAddWidget(forms.widgets.Select):
    template_name = "proteins/forms/widgets/select_add.html"


class ProteinForm(forms.ModelForm):
    """Form class for user-facing protein creation/submission form"""

    reference_doi = DOIField(required=False, help_text="e.g. 10.1038/nmeth.2413", label="Reference DOI")
    seq = SequenceField(required=False, help_text="Amino acid sequence", label="Sequence")
    # reference_pmid = forms.CharField(max_length=24, label='Reference Pubmed ID',
    #     required=False, help_text='e.g. 23524392 (must provide either DOI or PMID)')
    confirmation = forms.BooleanField(
        required=True,
        label=mark_safe(
            "<span class='small'>I understand that I am contributing to the <em>public</em> "
            "FPbase database, and confirm that I have verified the validity of the data</span>"
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        prot = cast("ProteinTF | None", getattr(self, "instance", None))
        if prot and prot.pk:
            for attr, field in [
                ("gene", "name"),
                ("aliases", "aliases"),
                # ("seq_validated", "seq"),
                ("primary_reference", "reference_doi"),
                # ("ipg_id", "ipg_id"),
                ("cofactor", "cofactor"),
                ("ENSEMBL", "ENSEMBL"),
                ("UNIPROT", "UNIPROT"),
                ("PDB", "PDB"),
            ]:
                if bool(getattr(prot, attr)):
                    self.fields[field].widget.attrs["readonly"] = True
            for attr, field in [
                # ("agg", "agg"),
                ("parent_organism", "parent_organism"),
                ("cofactor", "cofactor"),
                # ("switch_type", "switch_type"),
            ]:
                if bool(getattr(prot, attr)):
                    self.fields[field].widget.attrs["disabled"] = True

        self.helper = FormHelper(self)
        self.helper.form_tag = False
        self.helper.error_text_inline = True
        self.helper.layout = Layout(
            Field("confirmation", css_class="custom-checkbox"),
            Div(
                Div("name", css_class="col-md-4 col-sm-12"),
                Div("aliases", css_class="col-md-4 col-sm-6"),
                Div("reference_doi", css_class="col-md-4 col-sm-6"),
                css_class="row",
            ),
            # Div(
            #     Div("agg", css_class="col-sm-6"),
            #     Div("switch_type", css_class="col-sm-6"),
            #     css_class="row",
            # ),
            Div(
                Div("parent_organism", css_class="col-sm-8"),
                Div("cofactor", css_class="col-sm-4"),
                css_class="row",
            ),
            Div(
                # Div("ipg_id", css_class="col-lg-3 col-sm-6"),
                Div("ENSEMBL", css_class="col-lg-3 col-sm-6"),
                Div("UNIPROT", css_class="col-lg-3 col-sm-6"),
                Div("PDB", css_class="col-lg-3 col-sm-6"),
                css_class="row",
            ),
            # Div(Div("seq", css_class="col"), css_class="row"),
        )

    class Meta:
        model = ProteinTF
        fields = (
            "gene",
            # "ipg_id",
            "seq",
            # "agg",
            "parent_organism",
            "PDB",
            "reference_doi",
            "aliases",
            "ENSEMBL",
            "UNIPROT",
            "cofactor",
            # "switch_type",
        )
        labels = {"agg": "Oligomerization"}
        help_texts = {
            "aliases": "Comma separated list of aliases",
            "PDB": (
                'Comma separated list of <a class="text-info" '
                'href="https://www.rcsb.org/pdb/staticHelp.do?p=help/advancedsearch/pdbIDs.html"'
                ' target="_blank" rel="noopener">PDB IDs</a>'
            ),
            # "ipg_id": (
            #     'NCBI <a class="text-info" href="https://www.ncbi.nlm.nih.gov/ipg/docs/about/"'
            #     ' target="_blank" rel="noopener">Identical Protein Group ID</a>'
            # ),
            # "ENSEMBL": (
            #     'NCBI <a class="text-info" href="https://www.ncbi.nlm.nih.gov/genbank/sequenceids/"'
            #     ' target="_blank" rel="noopener">GenBank ID</a>'
            # ),
            "UNIPROT": (
                '<a class="text-info" href="https://www.uniprot.org/help/accession_numbers"'
                ' target="_blank" rel="noopener">UniProt accession number</a>'
            ),
            # "switch_type": (
            #     '<a class="text-info" href="https://help.fpbase.org/glossary#switch-type"'
            #     ' target="_blank">See help</a> for type classifications.'
            # ),
        }
        widgets = {"parent_organism": SelectAddWidget()}

    def clean_name(self):
        return check_existence(self, "name", self.cleaned_data["name"])

    def clean_seq(self):
        seq = self.cleaned_data["seq"]
        if set(seq) == set("ACTG"):
            raise forms.ValidationError("Please enter an amino acid sequence... not a DNA sequence.")
        self.cleaned_data["seq"] = "".join(seq.split()).upper()
        return check_existence(self, "seq", self.cleaned_data["seq"])

    def clean_ipg_id(self):
        return check_existence(self, "ipg_id", self.cleaned_data["ipg_id"])

    def clean_genbank(self):
        return check_existence(self, "genbank", self.cleaned_data["genbank"])

    def clean_uniprot(self):
        return check_existence(self, "uniprot", self.cleaned_data["uniprot"])

    def save_new_only(self, commit=True):
        # check the current db Instance for all of the changed_data values
        # if there is currently a non-null value in the database,
        # don't overwrite it ...
        # repopulate self.instance with form data afterwards, so that calling
        # self.save() again in the future WILL overwrite the database values
        isupdate = bool(hasattr(self, "instance") and self.instance.pk)
        backup = {}
        if not isupdate:
            return super().save(commit=commit)
        else:
            dbInstance = Protein.objects.get(pk=self.instance.pk)
            for field in self.changed_data:
                if not hasattr(dbInstance, field):
                    continue
                dbValue = getattr(dbInstance, field)
                formValue = getattr(self.instance, field)
                if field in ("pdb", "aliases"):
                    continue
                    for val in formValue:
                        if val not in dbValue:
                            getattr(self.instance, field).append(val)
                else:
                    if dbValue and formValue != dbValue:
                        backup[field] = formValue
                        setattr(self.instance, field, dbValue)
        self.instance = super().save(commit=commit)
        for field, value in backup.items():
            setattr(self.instance, field, value)
        return self.instance

class CollectionForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        self.proteins = kwargs.pop("proteins", None)
        super().__init__(*args, **kwargs)

    class Meta:
        model = ProteinCollection
        fields = ("name", "description", "private")

    def clean_name(self):
        name = self.cleaned_data["name"]
        # on update form allow for the same name (case insensitive)
        isupdate = bool(hasattr(self, "instance") and self.instance.pk)
        if isupdate and self.instance.name.lower() == name.lower():
            return name
        try:
            col = ProteinCollection.objects.get(name__iexact=name, owner=self.user)
        except ProteinCollection.DoesNotExist:
            return name

        raise forms.ValidationError(
            mark_safe(
                f'You already have a collection named <a href="{col.get_absolute_url()}" '
                f'style="text-decoration: underline;">{col.name}</a>'
            )
        )
