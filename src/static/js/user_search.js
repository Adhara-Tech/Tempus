/**
 * User Search Autocomplete for Tempus Admin
 * 
 * Usage:
 * setupUserSearch(textInputId, hiddenInputId, autoSubmit = false)
 */

function setupUserSearch(textInputId, hiddenInputId, autoSubmit = false) {
    const input = document.getElementById(textInputId);
    const hidden = document.getElementById(hiddenInputId);

    if (!input || !hidden) return;

    // Create results container if likely missing or just append next to input
    let resultsDiv = document.getElementById(textInputId + '_results');
    if (!resultsDiv) {
        resultsDiv = document.createElement('div');
        resultsDiv.id = textInputId + '_results';
        resultsDiv.className = 'list-group position-absolute';
        resultsDiv.style.zIndex = '1000';
        resultsDiv.style.width = input.offsetWidth + 'px'; // Match input width
        resultsDiv.style.maxHeight = '300px';
        resultsDiv.style.overflowY = 'auto';
        input.parentNode.style.position = 'relative'; // Ensure parent is relative
        input.parentNode.appendChild(resultsDiv);
    }

    let debounceTimer;

    input.addEventListener('input', function () {
        const query = this.value;

        clearTimeout(debounceTimer);

        if (query.length < 2) {
            resultsDiv.innerHTML = '';
            resultsDiv.style.display = 'none';
            return;
        }

        debounceTimer = setTimeout(() => {
            fetch(`/admin/api/usuarios/buscar?q=${encodeURIComponent(query)}`)
                .then(response => response.json())
                .then(data => {
                    resultsDiv.innerHTML = '';
                    if (data.results.length > 0) {
                        resultsDiv.style.display = 'block';
                        data.results.forEach(user => {
                            const item = document.createElement('a');
                            item.href = '#';
                            item.className = 'list-group-item list-group-item-action';
                            item.textContent = user.text;

                            item.addEventListener('click', function (e) {
                                e.preventDefault();
                                input.value = user.text;
                                hidden.value = user.id;
                                resultsDiv.style.display = 'none';

                                if (autoSubmit && input.form) {
                                    input.form.submit();
                                }
                            });

                            resultsDiv.appendChild(item);
                        });
                    } else {
                        resultsDiv.style.display = 'none';
                    }
                })
                .catch(err => console.error('Error searching users:', err));
        }, 300); // 300ms debounce
    });

    // Hide results when clicking outside
    document.addEventListener('click', function (e) {
        if (e.target !== input && e.target !== resultsDiv) {
            resultsDiv.style.display = 'none';
        }
    });

    // Clear selection if user clears text manually
    input.addEventListener('change', function () {
        if (this.value === '') {
            hidden.value = '';
            if (autoSubmit && this.form) {
                this.form.submit();
            }
        }
    });
}
