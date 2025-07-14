// import algoliasearch from 'algoliasearch/lite';
// import { autocomplete } from '@algolia/autocomplete-js';

export default async function initAutocomplete() {
    const searchClient = algoliasearch('I8J408MSCM', '7a38c6848180ee8d3723175b5ec3cc4e');

    const proteinIndex = searchClient.initIndex('ProteinTF_prod');
    const repeatIndex = searchClient.initIndex('Repeat_prod');
    const referenceIndex = searchClient.initIndex('Reference_prod');
    const organismIndex = searchClient.initIndex('Organism_prod');

    console.log('algoliasearch:', typeof algoliasearch);
    console.log('searchClient:', searchClient);
    console.log('index:', proteinIndex);
    console.log('autocomplete:', typeof autocomplete);

    autocomplete({
        container: '#algolia-search-input', // still required, but will wrap around input
        detachedMediaQuery: 'none',             // disables fullscreen modal mode
        placeholder: 'Search a protein or repeat',
        openOnFocus: true,
        inputElement: document.querySelector('#algolia-search-input'),
        onSubmit({ state }) {
            console.log("STATE: ", state)
            window.location.href = '/search/?q=' + state
        },
        getSources({ query }) {
            return [
            {
                sourceId: 'proteinTF',
                getItems() {
                    return proteinIndex.search(query, { hitsPerPage: 4 }).then(res => {
                        // console.log('Search results:', res.hits);
                        return res.hits;
                    });
                },
                templates: {
                header({ html }) {
                    return html`<div class="aa-header">Proteins</div>`;
                },
                item({ item, html }) {
                    var str = item.gene;
                    return html`<a href='/proteinTable/${item.gene}'><div>${str}</div></a>`;
                }
                }
            },
            {
                sourceId: 'repeat',
                getItems() {
                return repeatIndex.search(query, { hitsPerPage: 3 }).then(res => res.hits);
                },
                templates: {
                header({ html }) {5
                    return html`<div class="aa-header">Repeat</div>`;
                },
                item({ item, html }) {
                    var str = item.name;
                    return html`<a href='/repeatTable/${item.name}'><div>${str}</div></a>`;
                }
                }
            },
            {
                sourceId: 'reference',
                getItems() {
                return referenceIndex.search(query, { hitsPerPage: 3 }).then(res => res.hits);
                },
                templates: {
                header({ html }) {
                    return html`<div class="aa-header">Reference</div>`;
                },
                item({ item, html }) {
                    var str = item.title;
                    return html`<a href='${item.url}'><div>${str}</div></a>`;
                }
                }
            },
            {
                sourceId: 'organism',
                getItems() {
                return organismIndex.search(query, { hitsPerPage: 3 }).then(res => res.hits);
                },
                templates: {
                header({ html }) {
                    return html`<div class="aa-header">Organism</div>`;
                },
                item({ item, html }) {
                    var str = item.scientific_name;
                    return html `<a href='${item.url}'><div>${str}</div></a>`;
                }
                }
            },
            ];
        }
    });
}